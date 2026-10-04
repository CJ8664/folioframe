#!/usr/bin/env python3
"""SpectraFrame companion server.

Implements PROTOCOL.md v2.1:
  Public:
    GET  /                              welcome page (or console if signed in)
    GET  /login                         -> redirects to /
    POST /api/auth/token                {id_token, client_id} -> session
  Human (signed-in session; Google sign-in with the user's OWN OAuth
  client -- the admin configures no OAuth):
    GET  /claim                         pair-a-device page
    GET  /api/session, /api/account     session info + account (client id,
                                        photo source, Photos state)
    PATCH /api/account/client           rotate the account's OAuth client ID
    GET  /api/devices                   my devices
    POST /api/devices/claim             {code} claim a device to my account
    PATCH/DELETE /api/devices/{id}      rename / unpair (revokes token)
    POST /api/devices/{id}/photos/upload  multipart -> pinned override
    DELETE /api/devices/{id}/photos/override  clear override
    GET  /api/devices/{id}/preview      PNG of what the device shows
    POST /api/gphotos/setup            {client_secret} (write-only)
    GET  /api/gphotos/connect          -> Google consent (per-user client)
    GET  /api/gphotos/callback         OAuth callback (per-user)
    GET  /api/gphotos/status           per-user Photos state
    POST /api/gphotos/pick             start a picker import (per user)
    POST /api/gphotos/disconnect        revoke per-user Photos tokens
    POST /api/next                      rotate my devices' frames now
    POST /api/source                    {name} set my photo source
  Device (Authorization: Bearer <token>):
    POST /v1/device/register            {device_id,...} -> claim code
    POST /v1/device/claim               {device_id, claim_code} poll
    GET  /v1/device/frame               packed 4bpp frame, ETag + 304
    POST /v1/device/status              heartbeat
    POST /v1/device/unpair              device-initiated unpair
    GET  /v1/device/ota/version, /v1/device/ota/firmware.bin

Security: no anonymous access to any frame, photo, or device control.
The welcome page is the only public page. Each user's Photos credentials,
tokens, and photo cache are isolated per user.
Config: server/config.json (created with defaults on first run) -- holds
NO OAuth credentials; the admin only sets port/public_url/source defaults.
State: server/data/registry.json (users/devices/sessions, 0600).
"""
import http.server
import json
import os
import re
import threading
import time
import urllib.parse
from io import BytesIO

from PIL import Image

import pipeline
import sources.folder  # noqa: F401  (registers)
import sources.picsum  # noqa: F401
import sources.url  # noqa: F401
import sources.dashboard  # noqa: F401
import sources.google_photos  # noqa: F401
from sources import SOURCES
from sources.google_photos import (GPhotosController, PickerClient, PickFlow)
from auth import AuthManager, AuthError, SESSION_COOKIE, CLIENT_ID_RE
from devices import DeviceRegistry, AlreadyPaired, BadClaim, RateLimiter
from store import JsonStore, FirestoreStore
from blobs import LocalBlobStore, GCSBlobStore
from token_store import StoreTokenStore

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")
DATA_DIR = os.path.join(HERE, "data")
FW_PATH = os.path.join(HERE, "firmware", "firmware.bin")

W, H = 1200, 1600

DEFAULT_CONFIG = {
    "port": 8765,
    "source": "picsum",
    "rotation_minutes": 60,
    "quiet_start": "22:00",
    "quiet_end": "07:00",
    "dither": "floyd",
    "folder": {"dir": "~/Pictures/frame"},
    "picsum": {"width": 1200, "height": 1600},
    "url": {"template": "https://picsum.photos/seed/{seed}/1200/1600"},
    "dashboard": {"lat": 36.17, "lon": -115.14,
                  "timezone": "America/Los_Angeles"},
    "auth": {"allowlist": []},
}


def _to_min(hhmm):
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet(now_min, start, end):
    s, e = _to_min(start), _to_min(end)
    if s == e:
        return False
    if s < e:
        return s <= now_min < e
    return now_min >= s or now_min < e


class Server:
    def __init__(self, config_path=None, state_path=None, data_dir=None):
        cfg_path = config_path or CONFIG_PATH
        st_path = state_path or STATE_PATH
        self.data_dir = data_dir or DATA_DIR
        if not os.path.exists(cfg_path):
            with open(cfg_path, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            print(f"wrote default {cfg_path}")
        with open(cfg_path) as f:
            self.cfg = json.load(f)
        # Cloud Run: full config via env (values can come from Secret Manager).
        # Top-level keys in SPECTRA_CONFIG_JSON replace the file's keys.
        env_cfg = os.environ.get("SPECTRA_CONFIG_JSON")
        if env_cfg:
            self.cfg.update(json.loads(env_cfg))
        # NOTE: the admin configures NO OAuth here. Each user brings their
        # own Google OAuth client (welcome page); auth.allowlist optionally
        # restricts which Google accounts may sign in (empty = anyone).

        # ---- Firebase mode ------------------------------------------------
        # Enabled when config has firebase.project_id. On Cloud Run this
        # switches persistence to Firestore + Cloud Storage; without it
        # everything stays local (dev/home lab). Auth is direct Google
        # ID-token verification on both backends (no Firebase Auth setup).
        self.firebase_cfg = self.cfg.get("firebase", {})
        self.firebase_on = bool(self.firebase_cfg.get("project_id"))
        self.public_url = (self.cfg.get("public_url")
                           or self.firebase_cfg.get("public_url")
                           or os.environ.get("PUBLIC_URL", "")).rstrip("/")

        self.lock = threading.Lock()
        if self.firebase_on:
            project = self.firebase_cfg["project_id"]
            self.store = FirestoreStore(project_id=project)
            bucket = self.firebase_cfg.get("storage_bucket",
                                           f"{project}.appspot.com")
            self.blobs = GCSBlobStore(bucket)
        else:
            self.store = JsonStore(os.path.join(self.data_dir,
                                                "registry.json"))
            self.blobs = LocalBlobStore(self.data_dir)

        # Rotation state lives in the store so it survives container
        # restarts; one-time import from the legacy state.json file.
        # History is keyed "{user_sub}:{source}" (per-user unseen-first).
        rot = self.store.get("_service", "rotation")
        if rot is None and os.path.exists(st_path):
            try:
                with open(st_path) as f:
                    rot = json.load(f)
            except (ValueError, OSError):
                rot = None
        self.state = {"history": {}}
        if isinstance(rot, dict):
            self.state.update(rot)
        self._save_state()

        self.auth = AuthManager(self.store, self.cfg)
        self.devices = DeviceRegistry(self.store)
        self.ratelimit = RateLimiter()
        self._shared_sources = {}  # name -> Source (stateless, shared)
        self._photos = {}          # google sub -> GPhotosController
        self._frames = {}          # device_id -> current frame slot
        self.build = "1"

    # ---- per-user state -------------------------------------------------
    def _get_user(self, sub):
        return self.store.get("users", sub) or {}

    def _put_user(self, sub, user):
        self.store.put("users", sub, user)

    def _user_client(self, sub):
        """(oauth_client_id, photos_client_secret) for a user.

        Read fresh from the store on every call so client rotation takes
        effect without a restart. The secret is never returned by any API.
        """
        user = self._get_user(sub)
        return (user.get("oauth_client_id", ""),
                user.get("photos_client_secret", ""))

    def photos_for(self, sub):
        """Per-user Google Photos controller (bring-your-own OAuth).

        Tokens are stored per user, the photo cache is namespaced per user
        (blob prefix / cache dir). The server holds no Photos credentials
        of its own.
        """
        ctrl = self._photos.get(sub)
        if ctrl is None:
            ctrl = GPhotosController(
                self.cfg.get("port", 8765),
                token_store=StoreTokenStore(self.store, sub),
                blob_store=self.blobs,
                blob_prefix=f"users/{sub}/gphotos/",
                cache_dir=os.path.join(self.data_dir, "users", sub,
                                       "gphotos"),
                public_url=self.public_url or None,
                client_provider=lambda s=sub: self._user_client(s),
                store=self.store,
                states_key=f"gphotos_oauth_states:{sub}",
            )
            self._photos[sub] = ctrl
        return ctrl

    def _user_source_name(self, sub):
        name = (self._get_user(sub).get("source")
                or self.cfg.get("source", "picsum"))
        return name if name in SOURCES else "picsum"

    def _user_source(self, sub, name):
        if name == "google_photos":
            return self.photos_for(sub).source
        src = self._shared_sources.get(name)
        if src is None:
            src = self._shared_sources[name] = self._make_source(name)
        return src

    def _make_source(self, name):
        cls = SOURCES.get(name)
        if not cls:
            raise ValueError(f"unknown source {name}")
        return cls(dict(self.cfg.get(name, {})))

    def _save_state(self):
        self.store.put("_service", "rotation", self.state)

    def switch_source(self, sub, name):
        """Set a user's photo source (their devices follow)."""
        if name not in SOURCES:
            raise ValueError(f"unknown source {name}")
        user = self._get_user(sub)
        user["source"] = name
        self._put_user(sub, user)
        for dev in self.devices.user_devices(sub):
            try:
                self._rotate_device(dev)
            except Exception as e:
                print(f"switch_source rotate {dev['device_id']}: {e}")

    def gphotos_pick(self, sub):
        """Create a picker session and import in the background (per user)."""
        gp = self.photos_for(sub)
        if not gp.configured:
            raise RuntimeError("save your OAuth client secret first")
        if not gp.oauth.connected:
            raise RuntimeError("Google Photos not connected")
        client = PickerClient(gp.oauth)
        session = client.create_session()
        gp.pick_state = {"session_id": session["id"],
                         "picker_uri": session["pickerUri"],
                         "status": "waiting", "count": 0, "error": ""}

        def run():
            try:
                n = PickFlow(client, gp.cache_dir, blob_store=self.blobs,
                             blob_prefix=gp.blob_prefix).run(session["id"])
                gp.pick_state.update(status="done", count=n)
            except Exception as e:
                gp.pick_state.update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()
        return gp.pick_state["picker_uri"]

    # ---- per-device rotation -------------------------------------------
    def _in_quiet_now(self):
        now = time.localtime()
        now_min = now.tm_hour * 60 + now.tm_min
        return in_quiet(now_min, self.cfg.get("quiet_start", "22:00"),
                        self.cfg.get("quiet_end", "07:00"))

    def _rotate_device(self, dev):
        """Render the next frame for one device from its owner's source."""
        sub = dev.get("owner")
        name = self._user_source_name(sub)
        src = self._user_source(sub, name)
        hist_key = f"{sub}:{name}"
        hist = self.state["history"].get(hist_key, [])
        item = src.next_id(hist)
        if item is None:
            raise RuntimeError(f"source {name}: no items")
        img = src.load(item)
        frame = pipeline.process_image(img, W, H,
                                       self.cfg.get("dither", "floyd"))
        self._frames[dev["device_id"]] = {
            "frame": frame,
            "etag": pipeline.frame_etag(frame),
            "preview": pipeline.preview_png(frame, W, H),
            "source": name,
            "last_rotation": int(time.time()),
        }
        hist.append(item)
        self.state["history"][hist_key] = hist[-200:]
        self._save_state()
        print(f"rotated: {dev['device_id']} {name}/{item}")

    def _frame_due(self, dev):
        slot = self._frames.get(dev["device_id"])
        if slot is None:
            return True
        interval = self.cfg.get("rotation_minutes", 60) * 60
        return time.time() - slot["last_rotation"] >= interval

    def tick(self):
        """Background rotation tick: interval + quiet hours, per device."""
        if self._in_quiet_now():
            return
        for dev in self.store.all("devices").values():
            try:
                if self._frame_due(dev):
                    self._rotate_device(dev)
            except Exception as e:
                print(f"tick rotate {dev.get('device_id')}: {e}")

    def device_frame(self, dev):
        """(frame_bytes, etag): pinned override wins, else the device's own
        rotation slot.

        Lazy rotation on wake: on Cloud Run instances scale to zero, so
        rotation must also happen here, not only on the background thread.
        """
        slot = self._frames.get(dev["device_id"])
        if slot is None:
            # First frame for this device: always render (even in quiet
            # hours -- a freshly paired frame should not stay blank).
            try:
                self._rotate_device(dev)
            except Exception as e:
                print("first-frame rotate error:", e)
                return None, None
        elif not self._in_quiet_now() and self._frame_due(dev):
            try:
                self._rotate_device(dev)
            except Exception as e:  # keep serving the old frame
                print("lazy tick error:", e)
        etag = dev.get("override_etag")
        if etag:
            data = self.blobs.get(
                f"devices/{dev['device_id']}/override.frame")
            if data:
                return data, etag
        slot = self._frames.get(dev["device_id"])
        if slot is None:
            return None, None
        return slot["frame"], slot["etag"]

    def device_preview(self, dev):
        etag = dev.get("override_etag")
        if etag:
            data = self.blobs.get(
                f"devices/{dev['device_id']}/override.png")
            if data:
                return data
        slot = self._frames.get(dev["device_id"])
        if slot is None:
            try:
                self._rotate_device(dev)
            except Exception:
                return None
            slot = self._frames.get(dev["device_id"])
        return slot["preview"] if slot else None

    def set_override(self, device_id, img):
        """Pin an uploaded PIL image as this device's frame. Returns etag."""
        frame = pipeline.process_image(img, W, H,
                                       self.cfg.get("dither", "floyd"))
        etag = pipeline.frame_etag(frame)
        self.blobs.put(f"devices/{device_id}/override.frame", frame,
                       "application/octet-stream")
        self.blobs.put(f"devices/{device_id}/override.png",
                       pipeline.preview_png(frame, W, H), "image/png")
        return etag

    def clear_override_files(self, device_id):
        self.blobs.delete(f"devices/{device_id}/override.frame")
        self.blobs.delete(f"devices/{device_id}/override.png")

    def describe(self, sub=None):
        d = {
            "sources": sorted(SOURCES),
            "rotation_minutes": self.cfg.get("rotation_minutes"),
            "build": self.build,
        }
        if sub:
            d["source"] = self._user_source_name(sub)
            d["devices"] = [dev["device_id"]
                            for dev in self.devices.user_devices(sub)]
        return d


APP = None  # set in main()


# --------------------------------------------------------------------------
# HTTP layer
# --------------------------------------------------------------------------

def _parse_multipart(body, content_type):
    """Minimal multipart/form-data parser -> {field: (filename, data)}."""
    m = re.search(r'boundary=([^;]+)', content_type or "")
    if not m:
        return {}
    boundary = ("--" + m.group(1).strip().strip('"')).encode()
    out = {}
    for part in body.split(boundary):
        if b"\r\n\r\n" not in part:
            continue
        head, data = part.split(b"\r\n\r\n", 1)
        if data.endswith(b"\r\n"):
            data = data[:-2]
        fm = re.search(br'name="([^"]+)"(?:;\s*filename="([^"]*)")?', head)
        if not fm:
            continue
        out[fm.group(1).decode()] = (fm.group(2).decode() if fm.group(2)
                                     else "", data)
    return out


def _valid_redirect_origin(origin):
    """Validate the console's location.origin for OAuth redirect use.

    The Photos OAuth redirect_uri must exactly match a URI the user
    registered, so it is derived from the page the user is actually on.
    Restricted to https (or http on localhost) so it can't be pointed at
    an attacker's site.
    """
    try:
        u = urllib.parse.urlparse(origin or "")
    except Exception:
        return None
    if u.scheme not in ("http", "https") or not u.hostname:
        return None
    if u.scheme == "http" and u.hostname not in ("localhost", "127.0.0.1"):
        return None
    netloc = u.hostname
    if u.port and u.port not in (80, 443):
        netloc += f":{u.port}"
    return f"{u.scheme}://{netloc}"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    # ---- helpers ------------------------------------------------------
    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, "application/json", json.dumps(obj).encode(), extra)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            return None

    def _client_ip(self):
        return self.client_address[0]

    def _human(self):
        """(session_id, session, user_sub) or (None, None, None)."""
        sid, sess = APP.auth.session_from_cookie(
            self.headers.get("Cookie"))
        if not sess:
            return None, None, None
        return sid, sess, sess.get("sub")

    def _require_human(self):
        sid, sess, sub = self._human()
        if not sess:
            self._json(401, {"ok": False, "error": "sign in required"})
            return None
        return sid, sess, sub

    def _require_csrf(self, sess):
        token = (self.headers.get("X-CSRF-Token") or "")
        if not token:  # also accept form field
            length = int(self.headers.get("Content-Length", 0))
            ctype = self.headers.get("Content-Type", "")
            if "application/x-www-form-urlencoded" in ctype and length:
                body = self.rfile.read(length).decode()
                token = urllib.parse.parse_qs(body).get("csrf", [""])[0]
        if not APP.auth.check_csrf(sess, token):
            self._json(403, {"ok": False, "error": "bad csrf token"})
            return False
        return True

    def _device(self):
        """Device dict from Bearer token, or None."""
        authz = self.headers.get("Authorization", "")
        if not authz.startswith("Bearer "):
            return None
        return APP.devices.verify_token(authz[7:].strip())

    def _require_device(self):
        dev = self._device()
        if not dev:
            self._json(401, {"ok": False, "error": "device auth required"})
            return None
        return dev

    def _device_id_from_path(self, prefix):
        p = urllib.parse.urlparse(self.path).path
        if p.startswith(prefix):
            rest = p[len(prefix):]
            dev_id = rest.split("/")[0]
            if re.fullmatch(r"sf-[0-9a-f]{12}", dev_id):
                return dev_id, rest[len(dev_id):]
        return None, None

    def _set_session_cookie(self, session_id):
        val = APP.auth.cookie_value(session_id)
        return {"Set-Cookie":
                f"{SESSION_COOKIE}={val}; HttpOnly; Secure; "
                f"SameSite=Lax; Path=/; Max-Age={24*3600}"}

    # ---- GET ----------------------------------------------------------
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path

        if p == "/api/config":
            # Public client config. The Firebase web API key is designed to
            # be public (security comes from Auth + Firestore rules, both
            # server-enforced); nothing secret is exposed here.
            self._json(200, {"firebase": APP.firebase_cfg.get("web", {})})
            return

        if p == "/login":
            # Kept for old bookmarks; sign-in now starts at the welcome page.
            self._redirect("/")
            return

        if p == "/claim":
            if not self._human()[1]:
                self._redirect("/")
                return
            self._send(200, "text/html", CLAIM_HTML.encode())
            return

        if p == "/":
            # The only public page: a welcome page describing the steps.
            # Signed-in users get their console (account page) instead.
            if not self._human()[1]:
                legacy = APP.cfg.get("auth", {}).get("client_id", "")
                self._send(200, "text/html",
                            WELCOME_HTML(legacy).encode())
                return
            self._send(200, "text/html", CONSOLE_HTML.encode())
            return

        if p == "/api/session":
            got = self._require_human()
            if not got:
                return
            _, sess, sub = got
            user = APP.store.get("users", sub) or {}
            self._json(200, {"ok": True, "email": user.get("email", ""),
                             "csrf": sess.get("csrf", "")})
            return

        if p == "/api/account":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            user = APP._get_user(sub)
            gp = APP.photos_for(sub)
            self._json(200, {
                "ok": True,
                "email": user.get("email", ""),
                "name": user.get("name", ""),
                "client_id": user.get("oauth_client_id", ""),
                "source": APP._user_source_name(sub),
                "sources": sorted(SOURCES),
                "photos_secret_saved": bool(
                    user.get("photos_client_secret")),
                "photos_connected": gp.oauth.connected,
                "photos_cached": gp.cache_count(),
            })
            return

        if p == "/api/devices":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            devs = []
            for d in APP.devices.user_devices(sub):
                devs.append({
                    "device_id": d["device_id"], "name": d.get("name"),
                    "panel": d.get("panel"), "fw": d.get("fw"),
                    "last_seen": d.get("last_seen"),
                    "battery_mv": d.get("battery_mv"),
                    "battery_pct": d.get("battery_pct"),
                    "rssi": d.get("rssi"),
                    "override": bool(d.get("override_etag")),
                })
            self._json(200, {"ok": True, "devices": devs})
            return

        dev_id, rest = self._device_id_from_path("/api/devices/")
        if dev_id and rest == "/preview":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            dev = APP.store.get("devices", dev_id)
            if not dev or dev.get("owner") != sub:
                self._json(404, {"ok": False})
                return
            png = APP.device_preview(dev)
            if png is None:
                self.send_response(503)
                self.end_headers()
                return
            self._send(200, "image/png", png)
            return

        if p == "/v1/device/frame":
            dev = self._require_device()
            if not dev:
                return
            frame, etag = APP.device_frame(dev)
            if self.headers.get("If-None-Match") == etag and etag:
                self.send_response(304)
                self.end_headers()
                return
            if frame is None:
                self.send_response(503)
                self.end_headers()
                return
            self._send(200, "application/octet-stream", frame, {
                "ETag": etag, "X-Frame-Format": "packed4bpp"})
            return

        if p == "/v1/device/ota/version":
            if not self._require_device():
                return
            self._send(200, "text/plain", APP.build.encode())
            return

        if p == "/v1/device/ota/firmware.bin":
            if not self._require_device():
                return
            if os.path.exists(FW_PATH):
                with open(FW_PATH, "rb") as f:
                    self._send(200, "application/octet-stream", f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return

        if p == "/debug":
            got = self._require_human()
            if not got:
                return
            self._json(200, APP.describe(got[2]))
            return

        if p == "/api/gphotos/connect":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            gp = APP.photos_for(sub)
            if not gp.configured:
                self._json(400, {
                    "ok": False,
                    "error": "save your OAuth client secret on your "
                             "account page first"})
                return
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            origin = _valid_redirect_origin(q.get("origin", [""])[0])
            if not origin:
                self._json(400, {"ok": False, "error": "bad origin"})
                return
            redirect_uri = origin + "/api/gphotos/callback"
            state = gp.new_state(redirect_uri)
            self.send_response(302)
            self.send_header(
                "Location", gp.oauth.auth_url(state, redirect_uri))
            self.end_headers()
            return

        if p == "/api/gphotos/callback":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code, state = q.get("code", [""])[0], q.get("state", [""])[0]
            gp = APP.photos_for(sub)
            redirect_uri = gp.pop_state(state) if state else None
            if not code or not redirect_uri:
                self._send(400, "text/plain", b"bad oauth response")
            else:
                try:
                    gp.oauth.exchange_code(code, redirect_uri)
                    self._redirect("/")
                except Exception as e:
                    self._send(500, "text/plain",
                                f"connect failed: {e}".encode())
            return

        if p == "/api/gphotos/status":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            gp = APP.photos_for(sub)
            user = APP._get_user(sub)
            ps = gp.pick_state or {}
            # The client secret is write-only: never exposed here.
            self._json(200, {
                "client_id": user.get("oauth_client_id", ""),
                "secret_saved": bool(user.get("photos_client_secret")),
                "connected": gp.oauth.connected,
                "cached": gp.cache_count(),
                "picking": ps.get("status") == "waiting",
                "picker_uri": ps.get("picker_uri", ""),
                "pick_status": ps.get("status", ""),
                "pick_count": ps.get("count", 0),
                "pick_error": ps.get("error", ""),
            })
            return

        self.send_response(404)
        self.end_headers()

    # ---- POST ---------------------------------------------------------
    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path

        if p == "/api/auth/token":
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            # Bring-your-own-OAuth: the client ID belongs to the user, taken
            # from the welcome page. The server holds no OAuth client.
            # (No rate limit here: Google ID tokens can't be brute-forced --
            # forging one requires Google's signing keys -- and the endpoint
            # is no more expensive than the other public routes. The
            # guessable claim codes stay rate-limited.)
            client_id = (data.get("client_id") or "").strip()
            try:
                sub, email, name = APP.auth.verify_id_token(
                    data.get("id_token", ""), client_id)
            except AuthError as e:
                self._json(401, {"ok": False, "error": str(e)})
                return
            user = APP.store.get("users", sub) or {}
            if user.get("oauth_client_id") \
                    and user["oauth_client_id"] != client_id:
                self._json(401, {
                    "ok": False,
                    "error": "this account uses a different OAuth client -- "
                             "update it from your account page, then sign "
                             "in again"})
                return
            if not user.get("oauth_client_id"):
                user["oauth_client_id"] = client_id
                # One-time migration from the retired global setup wizard:
                # adopt its client into the account that signs in with it.
                legacy = APP.store.get("_service", "gphotos_client") or {}
                if legacy.get("client_id") == client_id \
                        and legacy.get("client_secret"):
                    user["photos_client_secret"] = legacy["client_secret"]
                if legacy:
                    APP.store.delete("_service", "gphotos_client")
            user.update({"email": email, "name": name,
                         "last_login": int(time.time())})
            APP.store.put("users", sub, user)
            session_id, csrf = APP.auth.create_session(sub)
            self._json(200, {"ok": True, "email": email, "csrf": csrf},
                       self._set_session_cookie(session_id))
            return

        if p == "/api/auth/logout":
            sid, _, _ = self._human()
            if sid:
                APP.auth.destroy_session(sid)
            self._json(200, {"ok": True}, {
                "Set-Cookie": f"{SESSION_COOKIE}=; HttpOnly; Secure; "
                              f"SameSite=Lax; Path=/; Max-Age=0"})
            return

        if p == "/v1/device/register":
            if not APP.ratelimit.check("reg:" + self._client_ip()):
                self._json(429, {"ok": False,
                                 "error": "rate limited, try again soon"})
                return
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            try:
                res = APP.devices.register(
                    data.get("device_id", ""), data.get("panel", ""),
                    data.get("fw", ""))
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e)})
                return
            self._json(201, {"ok": True, **res})
            return

        if p == "/v1/device/claim":
            if not APP.ratelimit.check("claim:" + self._client_ip()):
                self._json(429, {"ok": False,
                                 "error": "rate limited, try again soon"})
                return
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            try:
                res = APP.devices.poll_claim(
                    data.get("device_id", ""), data.get("claim_code", ""))
            except BadClaim:
                # Identical shape to "pending": no guessing oracle.
                self._json(200, {"ok": True, "status": "pending"})
                return
            self._json(200, {"ok": True, **res})
            return

        if p == "/v1/device/status":
            dev = self._require_device()
            if not dev:
                return
            data = self._read_json() or {}
            APP.devices.heartbeat(dev["device_id"], data)
            self._json(200, {"ok": True})
            return

        if p == "/v1/device/unpair":
            dev = self._require_device()
            if not dev:
                return
            APP.devices.device_self_unpair(dev["device_id"])
            self._json(200, {"ok": True})
            return

        if p == "/api/devices/claim":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            try:
                res = APP.devices.claim_by_code(data.get("code", ""), sub)
            except BadClaim:
                self._json(400, {"ok": False,
                                 "error": "invalid or expired code"})
                return
            except AlreadyPaired as e:
                self._json(409, {"ok": False, "error": str(e)})
                return
            self._json(200, {"ok": True, **res})
            return

        dev_id, rest = self._device_id_from_path("/api/devices/")
        if dev_id and rest == "/photos/upload":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            dev = APP.store.get("devices", dev_id)
            if not dev or dev.get("owner") != sub:
                self._json(404, {"ok": False})
                return
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            parts = _parse_multipart(body,
                                     self.headers.get("Content-Type", ""))
            file = parts.get("photo") or parts.get("file")
            if not file or not file[1]:
                self._json(400, {"ok": False,
                                 "error": "no photo uploaded"})
                return
            try:
                img = Image.open(BytesIO(file[1])).convert("RGB")
            except Exception:
                self._json(400, {"ok": False,
                                 "error": "not a readable image"})
                return
            etag = APP.set_override(dev_id, img)
            APP.devices.set_override_etag(dev_id, sub, etag)
            self._json(200, {"ok": True, "etag": etag,
                             "note": "pinned: shows on the device at its "
                                     "next wake"})
            return

        if p == "/api/gphotos/setup":
            # Save the user's Photos OAuth client secret. The client ID is
            # already on their account (from sign-in); one client does both.
            # The secret is write-only: no endpoint ever returns it.
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            secret = (data.get("client_secret") or "").strip()
            if not secret:
                self._json(400, {"ok": False,
                                 "error": "client_secret is required"})
                return
            user = APP._get_user(sub)
            user["photos_client_secret"] = secret
            APP._put_user(sub, user)
            self._json(200, {"ok": True})
            return

        if p == "/api/gphotos/pick":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            try:
                uri = APP.gphotos_pick(got[2])
                self._json(200, {"ok": True, "picker_uri": uri})
            except Exception as e:
                self._json(400, {"ok": False, "error": str(e)})
            return

        if p == "/api/gphotos/disconnect":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            APP.photos_for(got[2]).oauth.disconnect()
            self._json(200, {"ok": True})
            return

        if p == "/api/next":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            ok = True
            for dev in APP.devices.user_devices(got[2]):
                try:
                    APP._rotate_device(dev)
                except Exception:
                    ok = False
            self._json(200, {"ok": ok})
            return

        if p == "/api/source":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            try:
                APP.switch_source(got[2], data.get("name", ""))
                self._json(200, {"ok": True})
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e)})
            return

        self.send_response(404)
        self.end_headers()

    # ---- PATCH / DELETE ------------------------------------------------
    def do_PATCH(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/api/account/client":
            # Rotate the account's OAuth client ID (e.g. after creating a
            # new client). Takes effect on next sign-in; Photos keeps
            # working once the new client's secret is saved.
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            cid = (data.get("client_id") or "").strip()
            if not CLIENT_ID_RE.fullmatch(cid):
                self._json(400, {"ok": False,
                                 "error": "not a valid Google OAuth "
                                          "client ID"})
                return
            user = APP._get_user(sub)
            user["oauth_client_id"] = cid
            APP._put_user(sub, user)
            self._json(200, {"ok": True})
            return
        dev_id, rest = self._device_id_from_path("/api/devices/")
        if dev_id and not rest:
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            if APP.devices.rename(dev_id, sub, data.get("name", "")):
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False})
            return
        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        dev_id, rest = self._device_id_from_path("/api/devices/")
        if not dev_id:
            self.send_response(404)
            self.end_headers()
            return
        got = self._require_human()
        if not got or not self._require_csrf(got[1]):
            return
        _, _, sub = got
        if rest == "/photos/override":
            if APP.devices.clear_override(dev_id, sub):
                APP.clear_override_files(dev_id)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False})
            return
        if not rest:
            if APP.devices.unpair(dev_id, sub):
                APP.clear_override_files(dev_id)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False})
            return
        self.send_response(404)
        self.end_headers()

    def _redirect(self, where):
        self.send_response(302)
        self.send_header("Location", where)
        self.end_headers()


# --------------------------------------------------------------------------
# Console HTML
# --------------------------------------------------------------------------

def WELCOME_HTML(legacy_client_id=""):
    """Public welcome page: the only unauthenticated page.

    Describes the steps; the user enters their OWN Google OAuth client ID
    (bring-your-own model -- the admin configures no OAuth), then signs in
    with Google. Everything beyond this page requires the session.
    """
    prefill = legacy_client_id if CLIENT_ID_RE.fullmatch(
        legacy_client_id or "") else ""
    return f"""<html><head><meta name='viewport'
content='width=device-width,initial-scale=1'><title>SpectraFrame</title>
</head><body style='font-family:sans-serif;max-width:640px;margin:40px auto'>
<h2>SpectraFrame</h2>
<p>Your photos, on e-ink. This server belongs to whoever deployed it --
there is no central account system. You bring your own Google credentials;
nothing here is shared with anyone else.</p>
<h3>Get started (one time, about 5 minutes)</h3>
<ol>
<li>Create a <a href='https://console.cloud.google.com/'
target='_blank'>Google Cloud project</a> (any name).</li>
<li><b>APIs &amp; Services &rarr; OAuth consent screen</b>: choose
<b>External</b>, fill in the app name and your email. Under
<b>Test users</b>, add your Google account.</li>
<li><b>APIs &amp; Services &rarr; Credentials &rarr; Create Credentials
&rarr; OAuth client ID</b>: application type <b>Web application</b>.
Under <b>Authorized redirect URIs</b> add exactly:<br>
<code id='cburi'></code></li>
<li>Copy the <b>Client ID</b> and paste it below. One client does
everything: sign-in now, Google Photos later.</li>
</ol>
<input id='cid' placeholder='xxxx.apps.googleusercontent.com' size='50'
 value='{prefill}'>
<button onclick='cont()'>Continue</button>
<p id='err' style='color:red'></p>
<div id='signin' style='display:none'>
<p>Now sign in with the Google account you added as a test user:</p>
<script src='https://accounts.google.com/gsi/client' async defer></script>
<div id='gbtn'></div>
<p><small>Trouble? Google sign-in needs this page served over HTTPS
(or opened via <code>localhost</code>).</small></p>
</div>
<script>
document.getElementById('cburi').textContent =
  location.origin + '/api/gphotos/callback';
function cont(){{
  const cid = document.getElementById('cid').value.trim();
  if(!/^[A-Za-z0-9-]+\\.apps\\.googleusercontent\\.com$/.test(cid)){{
    document.getElementById('err').textContent =
      "That doesn't look like a Google OAuth client ID.";
    return;
  }}
  document.getElementById('err').textContent = '';
  document.getElementById('signin').style.display = 'block';
  window._cid = cid;
  google.accounts.id.initialize({{client_id: cid, callback: onGoogle}});
  google.accounts.id.renderButton(document.getElementById('gbtn'),
    {{type: 'standard'}});
}}
function onGoogle(r){{
  fetch('/api/auth/token', {{method: 'POST',
    headers: {{'Content-Type': 'application/json'}},
    body: JSON.stringify({{id_token: r.credential,
                          client_id: window._cid}})}})
  .then(r => r.json()).then(j => {{
    if(j.ok) location.href = '/';
    else document.getElementById('err').textContent = j.error;
  }});
}}
</script></body></html>"""


CONSOLE_HTML = """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1'><title>SpectraFrame</title>
</head><body style='font-family:sans-serif;max-width:640px;margin:20px auto'>
<h2>SpectraFrame console</h2>
<p><span id='who'></span> · <a href='/claim'>Pair a device</a> ·
<button onclick='logout()'>Sign out</button></p>
<div id='acct'></div>
<div id='devices'>loading…</div>
<h3>Photo source</h3>
<div id='src'></div>
<h3>Google Photos</h3>
<div id='photos'></div>
<script>
let CSRF='';
async function api(m,u,b,form){
  const o={method:m,headers:{'X-CSRF-Token':CSRF}};
  if(form){o.body=b;} else if(b){o.headers['Content-Type']='application/json';o.body=JSON.stringify(b);}
  const r=await fetch(u,o); return r.json().catch(()=>({}));
}
async function init(){
  const s=await (await fetch('/api/session')).json();
  if(!s.ok){location.href='/';return;}
  CSRF=s.csrf;
  const a=await (await fetch('/api/account')).json();
  document.getElementById('who').textContent=a.email;
  document.getElementById('acct').innerHTML=
    `<div style='border:1px solid #ccc;padding:12px;margin:12px 0'>
     <b>Account</b><br>Email: ${a.email}<br>
     OAuth client: <code>${a.client_id}</code>
     <button onclick='updClient()'>Update client ID</button><br>
     <small>Your own Google OAuth client — sign-in and Photos both use it.
     Only you can see this page's data.</small></div>`;
  const d=await (await fetch('/api/devices')).json();
  const el=document.getElementById('devices');
  if(!d.devices.length){el.innerHTML='<p>No devices yet. <a href="/claim">Pair one</a> — the code is on its screen.</p>';}
  else el.innerHTML='<h3>My devices</h3>'+d.devices.map(dev=>`
    <div style='border:1px solid #ccc;padding:12px;margin:12px 0'>
      <b>${dev.name}</b> <small>${dev.device_id}</small><br>
      <small>last seen: ${dev.last_seen?new Date(dev.last_seen*1000).toLocaleString():'never'}
      · battery: ${dev.battery_pct??'—'}% · fw: ${dev.fw??'—'}</small><br>
      ${dev.override?'<b>pinned photo active</b> <button onclick="clearOv(\\''+dev.device_id+'\\')">clear</button><br>':''}
      <img src='/api/devices/${dev.device_id}/preview' width='200'><br>
      <form onsubmit='return upload(event,"${dev.device_id}")'>
        <input type='file' name='photo' accept='image/*' required>
        <button>Push photo to device</button>
      </form><small>Push pins the photo immediately; the device shows it at its next wake.</small><br>
      <button onclick='renameDev("${dev.device_id}")'>Rename</button>
      <button onclick='unpair("${dev.device_id}")'>Unpair</button>
    </div>`).join('');
  document.getElementById('src').innerHTML=
    a.sources.map(n=>`<button ${n===a.source?'disabled':''}
      onclick="setSrc('${n}')">${n}</button>`).join(' ')+
    ` <button onclick='nextFrame()'>Next photo</button>`;
  const g=await (await fetch('/api/gphotos/status')).json();
  const ph=document.getElementById('photos');
  if(!g.secret_saved){
    ph.innerHTML=`<p>Your sign-in client: <code>${g.client_id}</code></p>
    <p>To enable Google Photos, paste this client's <b>client secret</b>
    (Google Cloud &rarr; Credentials &rarr; click your client):</p>
    <input id='gsec' type='password' size='50' placeholder='Client secret'>
    <button onclick='saveSecret()'>Save secret</button><p id='secmsg'></p>
    <p><small>Stored on this server only, never shown again. You can
    disconnect any time.</small></p>`;
  } else if(!g.connected){
    ph.innerHTML=`<p>Client secret saved.</p>
    <a href='/api/gphotos/connect?origin=${encodeURIComponent(location.origin)}'>
    <button>Connect Google Photos</button></a>
    <p><small>You'll approve access on Google's consent screen — one click,
    no secrets to copy.</small></p>`;
  } else {
    ph.innerHTML=`Connected · ${g.cached} cached
    <button onclick='gpick()'>Pick more photos</button>
    <button onclick='gdisc()'>Disconnect</button>`;
    if(g.picking) ph.innerHTML+=`<br><small>Picker open:
      <a href='${g.picker_uri}' target='_blank'>continue picking</a></small>`;
  }
}
async function updClient(){
  const cid=prompt('New OAuth client ID (xxxx.apps.googleusercontent.com):');
  if(!cid) return;
  const r=await api('PATCH','/api/account/client',{client_id:cid.trim()});
  alert(r.ok?'Saved — sign out and sign back in with the new client.':'Error: '+r.error);
  if(r.ok) init();
}
async function setSrc(n){
  const r=await api('POST','/api/source',{name:n});
  if(!r.ok) alert('Error: '+r.error); init();
}
async function nextFrame(){
  const r=await api('POST','/api/next');
  if(!r.ok) alert('Error: '+r.error); init();
}
async function saveSecret(){
  const sec=document.getElementById('gsec').value.trim();
  const r=await api('POST','/api/gphotos/setup',{client_secret:sec});
  document.getElementById('secmsg').textContent=
    r.ok?'Saved — now connect below.':('Error: '+r.error);
  if(r.ok) init();
}
async function gdisc(){
  if(!confirm('Disconnect Google Photos? Cached photos stay until you pick again.'))return;
  await api('POST','/api/gphotos/disconnect'); init();
}
async function upload(e,id){
  e.preventDefault();
  const fd=new FormData(e.target);
  const r=await api('POST','/api/devices/'+id+'/photos/upload',fd,true);
  alert(r.ok?'Pushed — shows on the device at its next wake.':('Error: '+r.error));
  init(); return false;
}
async function clearOv(id){
  if(!confirm('Clear the pinned photo and resume the normal source?'))return;
  await api('DELETE','/api/devices/'+id+'/photos/override'); init();
}
async function unpair(id){
  if(!confirm('Unpair this device? Its token is revoked immediately.'))return;
  await api('DELETE','/api/devices/'+id); init();
}
async function renameDev(id){
  const n=prompt('New name:'); if(n==null)return;
  await api('PATCH','/api/devices/'+id,{name:n}); init();
}
async function gpick(){
  const r=await api('POST','/api/gphotos/pick');
  if(r.ok&&r.picker_uri) open(r.picker_uri,'_blank'); else alert('Error: '+r.error);
}
async function logout(){await fetch('/api/auth/logout',{method:'POST'});location.href='/';}
init();
</script></body></html>"""

CLAIM_HTML = """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1'><title>Pair device</title>
</head><body style='font-family:sans-serif;max-width:480px;margin:40px auto'>
<h2>Pair a device</h2>
<p>Enter the 8-character code shown on the device's screen
(<code>XXXX-XXXX</code>).</p>
<input id='code' placeholder='XXXX-XXXX'
 style='font-size:1.4em;letter-spacing:2px;text-transform:uppercase'>
<button onclick='claim()' style='font-size:1.2em'>Pair</button>
<p id='msg'></p><p><a href='/'>back</a></p>
<script>
let CSRF='';
fetch('/api/session').then(r=>r.json()).then(s=>{CSRF=s.csrf||'';});
async function claim(){
  const code=document.getElementById('code').value;
  const r=await (await fetch('/api/devices/claim',{method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},
    body:JSON.stringify({code})})).json();
  document.getElementById('msg').textContent =
    r.ok?('Paired: '+(r.name||r.device_id)):('Error: '+r.error);
}
</script></body></html>"""


def main():
    global APP
    APP = Server()

    def ticker():
        while True:
            time.sleep(30)
            try:
                APP.tick()
            except Exception as e:
                print("tick error:", e)

    threading.Thread(target=ticker, daemon=True).start()
    # Cloud Run injects $PORT; local runs use config.json.
    port = int(os.environ.get("PORT", APP.cfg.get("port", 8765)))
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SpectraFrame server v2.1 on :{port} (frame {W}x{H})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
