#!/usr/bin/env python3
"""SpectraFrame companion server.

Implements PROTOCOL.md v2.1:
  Public:
    GET  /                              welcome page (or console if signed in)
    GET  /login                         -> redirects to /
    POST /api/auth/token                {id_token} -> session
    GET  /api/config                    public client config (Google client ID)
  Human (signed-in session; Google sign-in with the service's OAuth
  client -- the admin configures it once in "google"):
    GET  /claim                         pair-a-device page
    GET  /photos                        photo picker (thumbnails, e-ink
                                       preview, 3:4 editor)
    GET  /api/photos                    my photo library [{id, name}]
    GET  /api/photos/{id}/thumb         360px JPEG thumbnail
    GET  /api/photos/{id}/full          full-size JPEG
    POST /api/photos/{id}/edit          raw JPEG body -> replace cached photo
    GET  /api/session, /api/account     session info + account
    GET  /api/devices                   my devices
    POST /api/devices/claim             {code} claim a device to my account
    PATCH/DELETE /api/devices/{id}      rename / unpair (revokes token)
    POST /api/devices/{id}/photos/upload  multipart -> pinned override
    DELETE /api/devices/{id}/photos/override  clear override
    GET  /api/devices/{id}/preview      PNG of what the device shows
    GET  /api/gphotos/connect          -> Google consent (service client)
    GET  /api/gphotos/callback         OAuth callback (per-user tokens)
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
The welcome page is the only public page. Each user's Photos tokens and
photo cache are isolated per user; the OAuth client itself belongs to the
service (admin-configured once).
Config: server/config.json (created with defaults on first run), or
SPECTRA_CONFIG_JSON env (Portainer). The admin sets the Google OAuth
client once under "google"; auth.allowlist optionally gates sign-in.
State: server/data/registry.json (users/devices/sessions, 0600).
"""
import http.server
import hashlib
import json
import os
import uuid
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
import sources.uploads  # noqa: F401  (registers UploadsSource)
from sources import SOURCES
from sources.google_photos import (GPhotosController, PickerClient, PickFlow)
from auth import AuthManager, AuthError, SESSION_COOKIE
from devices import DeviceRegistry, AlreadyPaired, BadClaim, RateLimiter
from store import JsonStore, FirestoreStore
from blobs import LocalBlobStore, GCSBlobStore
from token_store import StoreTokenStore

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")
DATA_DIR = os.path.join(HERE, "data")
FW_PATH = os.path.join(HERE, "firmware", "firmware.bin")
FW_DIR = os.path.join(HERE, "firmware")
# Web-flash parts for the ESP32-S3 (offsets per the ESP-IDF S3 flash layout;
# matches what `pio run` produces for the ee02 env). All four must be
# published for /flash to be offered.
FLASH_PARTS = [
    ("bootloader.bin", 0),
    ("partitions.bin", 32768),    # 0x8000
    ("boot_app0.bin", 57344),     # 0xe000
    ("firmware.bin", 65536),      # 0x10000
]

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
    # Firmware OTA: bump "build" (integer) whenever you publish a new
    # server/firmware/firmware.bin. Devices whose FW_BUILD is lower will
    # download and flash it (battery-gated, MD5-verified).
    "build": "5",
    # Shown on the public /flash page and in its esp-web-tools manifest.
    # Keep in sync with FW_VERSION in src/main.cpp.
    "fw_version": "3.2.0",
    # The service's Google OAuth client (admin one-time setup): used for
    # "Sign in with Google" and for Google Photos. Users never see these
    # values. Get them from Google Cloud Console -> your project ->
    # APIs & Services -> Credentials -> your Web OAuth client.
    "google": {"client_id": "", "client_secret": ""},
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
        # NOTE: the admin configures the service's Google OAuth client once
        # under "google" (client_id + client_secret). auth.allowlist
        # optionally restricts which Google accounts may sign in
        # (empty = anyone; accounts are isolated per user).

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
        # OTA build number: BUILD file (written by package_firmware.sh from
        # the firmware's FW_BUILD) wins; config/env is the fallback.
        self.build = str(self.cfg.get("build", "1"))
        try:
            with open(os.path.join(FW_DIR, "BUILD")) as f:
                b = f.read().strip()
                if b.isdigit():
                    self.build = b
        except OSError:
            pass

    # ---- per-user state -------------------------------------------------
    def _get_user(self, sub):
        return self.store.get("users", sub) or {}

    def _put_user(self, sub, user):
        self.store.put("users", sub, user)

    def _google_creds(self):
        """The service's Google OAuth client (admin-configured, once)."""
        g = self.cfg.get("google", {})
        return (g.get("client_id", ""), g.get("client_secret", ""))

    def google_configured(self):
        cid, csec = self._google_creds()
        return bool(cid and csec)

    def flash_available(self):
        """True when all four web-flash binaries are published."""
        return all(os.path.isfile(os.path.join(FW_DIR, name))
                   for name, _ in FLASH_PARTS)

    def fw_version(self):
        """Version of the published firmware. Single source of truth is the
        VERSION file written by tools/package_firmware.sh from the firmware's
        FW_VERSION; the config value is only a fallback."""
        try:
            with open(os.path.join(FW_DIR, "VERSION")) as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            pass
        return self.cfg.get("fw_version", "0.0.2")

    def fw_versions(self):
        """All published firmware versions, newest first. Discovered from
        versioned binaries (firmware-<x.y.z>.bin) in the firmware dir."""
        import re
        versions = []
        try:
            names = os.listdir(FW_DIR)
        except OSError:
            names = []
        for n in names:
            m = re.fullmatch(r"firmware-(\d+\.\d+\.\d+)\.bin", n)
            if m:
                versions.append(m.group(1))
        versions.sort(key=lambda v: tuple(int(x) for x in v.split(".")),
                      reverse=True)
        return versions

    def fw_md5(self):
        """MD5 of the published firmware.bin, cached by (size, mtime) so
        the OTA version endpoint doesn't re-hash the file on every request."""
        try:
            st = os.stat(FW_PATH)
        except OSError:
            return None
        key = (st.st_size, st.st_mtime_ns)
        cached = getattr(self, "_fw_md5_cache", None)
        if cached and cached[0] == key:
            return cached[1]
        h = hashlib.md5()
        with open(FW_PATH, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        digest = h.hexdigest()
        self._fw_md5_cache = (key, digest)
        return digest

    def fw_bin_for(self, version):
        """File name of the firmware binary for a version, or None."""
        import re
        if not re.fullmatch(r"\d+\.\d+\.\d+", version or ""):
            return None
        name = f"firmware-{version}.bin"
        if os.path.isfile(os.path.join(FW_DIR, name)):
            return name
        return None

    def uploads_dir(self, sub):
        """Per-user uploads directory (created on demand)."""
        d = os.path.join(self.data_dir, "users", sub, "uploads")
        os.makedirs(d, exist_ok=True)
        return d

    def photos_for(self, sub):
        """Per-user Google Photos controller (shared service OAuth client).

        The OAuth client ID/secret belong to the service; tokens are stored
        per user and the photo cache is namespaced per user (blob prefix /
        cache dir).
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
                # Resolved per call so config changes take effect
                # without a restart.
                client_provider=lambda: self._google_creds(),
                store=self.store,
                states_key=f"gphotos_oauth_states:{sub}",
            )
            self._photos[sub] = ctrl
        return ctrl

    def _user_source_name(self, sub):
        name = (self._get_user(sub).get("source")
                or self.cfg.get("source", "picsum"))
        return name if name in SOURCES else "picsum"

    def _all_user_photos(self, sub):
        """Aggregate photos from google_photos and uploads sources.
        
        Returns list of (namespaced_id, display_name, source_name) tuples.
        Namespaced IDs are like 'gphotos:ABC123.jpg' or 'uploads:xyz.jpg'.
        """
        photos = []
        # Google Photos
        try:
            gp_source = self._user_source(sub, "google_photos")
            for pid in gp_source._ids():
                photos.append((f"gphotos:{pid}", pid, "google_photos"))
        except Exception:
            pass
        # Uploads
        try:
            up_source = self._user_source(sub, "uploads")
            for pid in up_source._ids():
                photos.append((f"uploads:{pid}", pid, "uploads"))
        except Exception:
            pass
        return photos

    def _resolve_namespaced_id(self, sub, namespaced_id):
        """Parse 'gphotos:ABC.jpg' -> (source_obj, real_id, source_name).
        
        Falls back to active source for un-namespaced IDs (backward compat).
        Returns (None, None, None) if not found.
        """
        if ":" in namespaced_id:
            prefix, real_id = namespaced_id.split(":", 1)
            if prefix == "gphotos":
                src = self._user_source(sub, "google_photos")
                if real_id in src._ids():
                    return src, real_id, "google_photos"
            elif prefix == "uploads":
                src = self._user_source(sub, "uploads")
                if real_id in src._ids():
                    return src, real_id, "uploads"
            return None, None, None
        else:
            # Backward compat: un-namespaced ID uses active source
            src = self.photos_for(sub).source
            if namespaced_id in src._ids():
                return src, namespaced_id, self._user_source_name(sub)
            return None, None, None

    def _user_source(self, sub, name):
        if name == "google_photos":
            return self.photos_for(sub).source
        if name == "uploads":
            key = f"uploads:{sub}"
            src = self._shared_sources.get(key)
            if src is None:
                src = self._shared_sources[key] = SOURCES["uploads"]({
                    "dir": os.path.join(self.data_dir, "users", sub,
                                        "uploads")})
            return src
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
        if not self.google_configured():
            raise RuntimeError("Google Photos isn't set up on this server yet")
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
                                       self.cfg.get("dither", "floyd"),
                                       self.cfg.get("tone"))
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
                                       self.cfg.get("dither", "floyd"),
                                       self.cfg.get("tone"))
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
        # Block MIME sniffing: text/plain error bodies must never be
        # interpreted as HTML (XSS via sniffed error content).
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj, extra=None):
        self._send(code, "application/json", json.dumps(obj).encode(), extra)

    def _static(self, name, ctype, extra=None):
        # Serves a file from server/static/. Path traversal is blocked by
        # the caller (no slashes allowed in `name`).
        path = os.path.join(STATIC_DIR, name)
        if not os.path.isfile(path):
            self._json(404, {"ok": False, "error": "not found"})
            return
        with open(path, "rb") as f:
            self._send(200, ctype, f.read(), extra)

    def _read_json(self, max_bytes=1024 * 1024):
        # Cap request bodies: an unbounded read lets anyone (even
        # unauthenticated, on public routes) exhaust server memory.
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return None
        if length < 0 or length > max_bytes:
            return None
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw.decode() or "{}")
        except (ValueError, UnicodeDecodeError):
            return None

    # Direct peers trusted to set X-Forwarded-For (reverse proxies /
    # tunnels in front of this server). Without this, every client behind
    # the Cloudflare Tunnel shares one peer IP and a single rate-limit
    # bucket -- one bad actor could lock out pairing globally. Never trust
    # XFF from an untrusted peer: it's trivially spoofable.
    TRUSTED_PROXY_IPS = frozenset(
        ip.strip()
        for ip in os.environ.get("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
        if ip.strip()
    )

    def _client_ip(self):
        peer = self.client_address[0]
        if peer in self.TRUSTED_PROXY_IPS:
            xff = self.headers.get("X-Forwarded-For")
            if xff:
                # Leftmost entry is the original client; proxies append
                # to the right.
                first = xff.split(",")[0].strip()
                if first:
                    return first
        return peer

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
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0
            ctype = self.headers.get("Content-Type", "")
            # Cap the form read: a CSRF token field never needs more than
            # a few KB. (The JSON body path caps at 1 MB; this must not be
            # the unbounded one.)
            if ("application/x-www-form-urlencoded" in ctype and
                    0 < length <= 65536):
                try:
                    body = self.rfile.read(length).decode()
                except (UnicodeDecodeError, ValueError):
                    body = ""
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
            if re.fullmatch(r"ff-[0-9a-f]{12}", dev_id):
                return dev_id, rest[len(dev_id):]
        return None, None

    def _photo_id_from_path(self, prefix, sub):
        """(item_id, rest) for /api/photos/<id>/... paths, else (None, None).

        The id must be one of the user's own cached photo ids -- never a
        raw path -- so this rejects traversal and cross-user guessing
        alike.
        """
        p = urllib.parse.urlparse(self.path).path
        if not p.startswith(prefix):
            return None, None
        rest = p[len(prefix):]
        raw_id = rest.split("/")[0]
        item_id = urllib.parse.unquote(raw_id)
        # Handle namespaced IDs (gphotos:xxx, uploads:xxx)
        src, real_id, _ = APP._resolve_namespaced_id(sub, item_id)
        if src is None:
            return None, None
        return item_id, rest[len(raw_id):]

    def _photo_bytes(self, sub, item_id, thumb=False):
        """Load a cached photo; thumbnail or full-size JPEG bytes."""
        src, real_id, _ = APP._resolve_namespaced_id(sub, item_id)
        if src is None:
            raise FileNotFoundError(item_id)
        img = src.load(real_id)
        if thumb:
            img.thumbnail((360, 480), Image.LANCZOS)
            q = 82
        else:
            q = 92
        buf = BytesIO()
        img.save(buf, "JPEG", quality=q)
        return buf.getvalue()

    def _set_session_cookie(self, session_id):
        val = APP.auth.cookie_value(session_id)
        return {"Set-Cookie":
                f"{SESSION_COOKIE}={val}; HttpOnly; Secure; "
                f"SameSite=Lax; Path=/; Max-Age={24*3600}"}

    # ---- GET ----------------------------------------------------------
    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path

        if p == "/manifest.webmanifest":
            self._static("manifest.webmanifest",
                         "application/manifest+json")
            return

        if p == "/flash":
            self._send(200, "text/html", _flash_page(
                APP.flash_available(),
                APP.fw_version(),
                APP.fw_versions()).encode(),
                {"Cache-Control": "no-store"})
            return

        if p == "/flash/manifest.json":
            if not APP.flash_available():
                self._json(404, {"ok": False,
                                 "error": "no firmware published"})
                return
            # ?version=x.y.z selects a published older build; default latest.
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            req_ver = (q.get("version") or [""])[0]
            if req_ver:
                fw_bin = APP.fw_bin_for(req_ver)
                if not fw_bin:
                    self._json(404, {"ok": False,
                                     "error": "unknown firmware version"})
                    return
                ver = req_ver
            else:
                fw_bin = "firmware.bin"
                ver = APP.fw_version()
            parts = [(n if n != "firmware.bin" else fw_bin, o)
                     for n, o in FLASH_PARTS]
            self._json(200, {
                "name": "FolioFrame",
                "version": ver,
                "builds": [{
                    "chipFamily": "ESP32-S3",
                    "parts": [
                        {"path": f"/flash/{name}", "offset": offset}
                        for name, offset in parts
                    ],
                }],
            })
            return

        if p.startswith("/flash/") and p.endswith(".bin"):
            part = p[len("/flash/"):]
            # Strict allowlist: the four published parts (flat names), plus
            # versioned firmware binaries (firmware-x.y.z.bin) for the
            # version picker. The regex rejects any path traversal.
            allowed = [n for n, _ in FLASH_PARTS]
            if part not in allowed:
                if not (re.fullmatch(r"firmware-\d+\.\d+\.\d+\.bin", part) and
                        APP.fw_bin_for(part[len("firmware-"):-len(".bin")])):
                    self._json(404, {"ok": False, "error": "not found"})
                    return
            if "/" in part:
                self._json(404, {"ok": False, "error": "not found"})
                return
            path = os.path.join(FW_DIR, part)
            if not os.path.isfile(path):
                self._json(404, {"ok": False, "error": "not found"})
                return
            with open(path, "rb") as f:
                # Never cache firmware binaries: a stale cached binary would
                # silently flash an outdated build (seen with 2.0.0 vs 3.0.0).
                self._send(200, "application/octet-stream", f.read(),
                           {"Cache-Control": "no-store"})
            return

        if p == "/sw.js":
            # Service workers must not be cached aggressively.
            self._static("sw.js", "application/javascript",
                         {"Cache-Control": "no-cache"})
            return

        if p.startswith("/static/esp-web-tools/"):
            name = p[len("/static/esp-web-tools/"):]
            # Only the vendored esp-web-tools chunks, flat in that dir.
            if (not name or "/" in name or name.startswith(".") or
                    not name.endswith(".js")):
                self._json(404, {"ok": False, "error": "not found"})
                return
            self._static("esp-web-tools/" + name, "application/javascript",
                         {"Cache-Control": "public, max-age=86400"})
            return

        if p.startswith("/static/"):
            name = p[len("/static/"):]
            if not name or "/" in name or name.startswith("."):
                self._json(404, {"ok": False, "error": "not found"})
                return
            ctype = {".png": "image/png", ".jpg": "image/jpeg",
                     ".css": "text/css",
                     ".svg": "image/svg+xml", ".ico": "image/x-icon",
                     ".webmanifest": "application/manifest+json",
                     ".js": "application/javascript"}.get(
                os.path.splitext(name)[1].lower(),
                "application/octet-stream")
            self._static(name, ctype,
                         {"Cache-Control": "public, max-age=86400"})
            return

        if p == "/api/config":
            # Public client config. The Google OAuth client ID is designed
            # to be public (it appears in the page's JavaScript); the client
            # secret is never exposed here.
            self._json(200, {"firebase": APP.firebase_cfg.get("web", {}),
                             "google_client_id": APP.auth.client_id})
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
            # The only public page: a welcome page with sign-in.
            # Signed-in users get their console (account page) instead.
            if not self._human()[1]:
                self._send(200, "text/html", WELCOME_HTML().encode())
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
                "source": APP._user_source_name(sub),
                "sources": sorted(SOURCES),
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
                    "fw_build": d.get("fw_build"),
                    "last_seen": d.get("last_seen"),
                    "battery_mv": d.get("battery_mv"),
                    "battery_pct": d.get("battery_pct"),
                    "rssi": d.get("rssi"),
                    "override": bool(d.get("override_etag")),
                })
            self._json(200, {"ok": True, "devices": devs,
                             "latest_fw": APP.fw_version(),
                             "latest_build": int(APP.build)})
            return

        if p == "/photos":
            # Photo picker page (thumbnail grid, e-ink preview, editor).
            if not self._human()[1]:
                self._redirect("/")
                return
            self._send(200, "text/html", PHOTOS_HTML().encode(),
                       {"Cache-Control": "no-store"})
            return

        if p == "/api/photos":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            try:
                photos = APP._all_user_photos(sub)
            except Exception:
                photos = []
            self._json(200, {"ok": True,
                             "photos": [{"id": nid, "name": name,
                                         "source": src}
                                        for nid, name, src in photos]})
            return

        if p.startswith("/api/photos/"):
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            item_id, rest = self._photo_id_from_path("/api/photos/", sub)
            if item_id and rest == "/thumb":
                try:
                    data = self._photo_bytes(sub, item_id, thumb=True)
                except Exception:
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                self._send(200, "image/jpeg", data,
                           {"Cache-Control": "private, max-age=3600"})
                return
            if item_id and rest == "/meta":
                src, real_id, _ = APP._resolve_namespaced_id(sub, item_id)
                meta = src.get_metadata(real_id) if src else None
                if meta is None:
                    self._json(404, {"ok": False, "error": "not found"})
                else:
                    self._json(200, {"ok": True, "metadata": meta})
                return
            if item_id and rest == "/full":
                try:
                    data = self._photo_bytes(sub, item_id)
                except Exception:
                    self._json(404, {"ok": False, "error": "not found"})
                    return
                self._send(200, "image/jpeg", data,
                           {"Cache-Control": "private, max-age=3600"})
                return
            self._json(404, {"ok": False, "error": "not found"})
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
            # Manifest format the firmware parses (see OtaManifest.cpp):
            # "build=N\n". An "md5=<hex>\n" line is added when a firmware
            # binary is published so the device verifies what it flashes
            # (matters because the device skips TLS cert validation).
            manifest = f"build={APP.build}\n"
            md5 = APP.fw_md5()
            if md5:
                manifest += f"md5={md5}\n"
            self._send(200, "text/plain", manifest.encode())
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
            if not APP.google_configured():
                self._json(400, {
                    "ok": False,
                    "error": "Google Photos isn't set up on this server "
                             "yet (the admin needs to add the Google "
                             "OAuth client first)"})
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
                    # Never echo provider exception details to the browser
                    # (they can contain response bodies); log server-side.
                    print(f"gphotos OAuth exchange failed for {sub}: "
                          f"{type(e).__name__}")
                    self._send(500, "text/plain",
                               b"connect failed: please try again")
            return

        if p == "/api/uploads":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            d = APP.uploads_dir(sub)
            items = []
            for f in sorted(os.listdir(d)):
                if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp",
                                       ".bmp")):
                    items.append({"name": f,
                                  "url": f"/api/uploads/file/{f}"})
            self._json(200, {"ok": True, "photos": items})
            return

        if p.startswith("/api/uploads/file/"):
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            name = p[len("/api/uploads/file/"):]
            if (not name or "/" in name or name.startswith(".") or
                    ".." in name):
                self._json(404, {"ok": False})
                return
            path = os.path.join(APP.uploads_dir(sub), name)
            if not os.path.isfile(path):
                self._json(404, {"ok": False})
                return
            ctype = {".png": "image/png", ".jpg": "image/jpeg",
                     ".jpeg": "image/jpeg", ".webp": "image/webp",
                     ".bmp": "image/bmp"}.get(
                os.path.splitext(name)[1].lower(), "application/octet-stream")
            with open(path, "rb") as f:
                self._send(200, ctype, f.read(),
                           {"Cache-Control": "private, max-age=3600"})
            return

        if p == "/api/gphotos/status":
            got = self._require_human()
            if not got:
                return
            _, _, sub = got
            gp = APP.photos_for(sub)
            ps = gp.pick_state or {}
            self._json(200, {
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
            id_token = data.get("id_token", "")
            # The Google ID token is verified against the service's own
            # OAuth client (admin-configured). No rate limit here: Google
            # ID tokens can't be brute-forced -- forging one requires
            # Google's signing keys -- and the endpoint is no more
            # expensive than the other public routes. The guessable claim
            # codes stay rate-limited.
            try:
                sub, email, name = APP.auth.verify_id_token(id_token)
            except AuthError as e:
                self._json(401, {"ok": False, "error": str(e)})
                return
            user = APP.store.get("users", sub) or {}
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
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 25 * 1024 * 1024:
                self._json(400, {"ok": False,
                                 "error": "photo too large (max 25 MB)"})
                return
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

        if p == "/api/uploads":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = 0
            if length <= 0 or length > 25 * 1024 * 1024:
                self._json(400, {"ok": False,
                                 "error": "photo too large (max 25 MB)"})
                return
            body = self.rfile.read(length) if length else b""
            parts = _parse_multipart(body,
                                     self.headers.get("Content-Type", ""))
            saved = []
            d = APP.uploads_dir(sub)
            for field, (fname, data) in parts.items():
                if not data:
                    continue
                try:
                    img = Image.open(BytesIO(data)).convert("RGB")
                except Exception:
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in (".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                    ext = ".jpg"
                name = f"{uuid.uuid4().hex}{ext}"
                # Re-encode to strip metadata and normalize.
                img.save(os.path.join(d, name))
                saved.append(name)
            if not saved:
                self._json(400, {"ok": False,
                                 "error": "no readable images uploaded"})
                return
            self._json(200, {"ok": True, "saved": saved,
                             "count": len(saved)})
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

        if p.startswith("/api/photos/") and p.endswith("/edit"):
            # Save an edited photo (photo picker "Apply"): replaces the
            # cached photo so the frame picks the edited version up on its
            # next rotation. Body is a raw JPEG (canvas.toBlob), CSRF via
            # the X-CSRF-Token header.
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            item_id, rest = self._photo_id_from_path("/api/photos/", sub)
            if not item_id or rest != "/edit":
                self._json(404, {"ok": False, "error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except (TypeError, ValueError):
                length = -1
            if length <= 0 or length > 15 * 1024 * 1024:
                self._json(400, {"ok": False, "error": "bad upload size"})
                return
            raw = self.rfile.read(length)
            try:
                # Validates the bytes are a real image (and caps decoded
                # pixels via pipeline.MAX_IMAGE_PIXELS); EXIF-normalizes.
                img = pipeline.load_image(raw)
            except Exception:
                self._json(400, {"ok": False, "error": "not an image"})
                return
            buf = BytesIO()
            img.save(buf, "JPEG", quality=92)
            try:
                src, real_id, _ = APP._resolve_namespaced_id(sub, item_id)
                if src is None:
                    raise FileNotFoundError(item_id)
                src.save(real_id, buf.getvalue())
            except Exception:
                self._json(500, {"ok": False, "error": "save failed"})
                return
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
        p = urllib.parse.urlparse(self.path).path
        if p.startswith("/api/uploads/"):
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            _, _, sub = got
            name = p[len("/api/uploads/"):]
            if (not name or "/" in name or name.startswith(".") or
                    ".." in name):
                self._json(404, {"ok": False})
                return
            path = os.path.join(APP.uploads_dir(sub), name)
            if os.path.isfile(path):
                os.remove(path)
                self._json(200, {"ok": True})
            else:
                self._json(404, {"ok": False})
            return
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

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

def _static_ver(name):
    """Content-hash version for cache-busting static URLs."""
    try:
        with open(os.path.join(STATIC_DIR, name), "rb") as f:
            return hashlib.md5(f.read()).hexdigest()[:8]
    except OSError:
        return "0"

# ---------------------------------------------------------------------------
# Frosted-glass design system (iOS HIG + Umbrel 2.0 inspired).
# Dark-first; light mode via prefers-color-scheme. Mobile-first layout.
# ---------------------------------------------------------------------------
THEME_CSS = ("<link rel='stylesheet' href='/static/farvist.min.css?v=" +
             _static_ver("farvist.min.css") + "'>" +
             "<link rel='stylesheet' href='/static/farvist-warm-clay.css?v=" +
             _static_ver("farvist-warm-clay.css") + "'>" +
             "<link rel='stylesheet' href='/static/folioframe.css?v=" +
             _static_ver("folioframe.css") + "'>")

PWA_HEAD = """
<meta charset='utf-8'>
<link rel='manifest' href='/manifest.webmanifest'>
<meta name='theme-color' content='#d9d1c4'>
<meta name='mobile-web-app-capable' content='yes'>
<meta name='apple-mobile-web-app-capable' content='yes'>
<meta name='apple-mobile-web-app-status-bar-style' content='default'>
<meta name='apple-mobile-web-app-title' content='FolioFrame'>
<link rel='apple-touch-icon' href='/static/icon-180.png'>
<link rel='icon' type='image/png' sizes='192x192' href='/static/icon-192.png'>
<script>
(function(){try{
  var t=localStorage.getItem('folioframe-theme');
  if(!t){t=window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light';}
  document.documentElement.dataset.theme=t;
  if(t==='dark')document.documentElement.classList.add('dark');
}catch(e){}})();
function ffThemeToggle(){
  try{
    var el=document.documentElement;
    var d=el.classList.toggle('dark');
    el.dataset.theme=d?'dark':'light';
    localStorage.setItem('folioframe-theme',d?'dark':'light');
  }catch(e){}
}
</script>
"""

SW_REGISTER = """
<script>
if('serviceWorker' in navigator){
  window.addEventListener('load',function(){
    navigator.serviceWorker.register('/sw.js').catch(function(){});
  });
}
(function(){
  var btn=document.getElementById('installbtn');
  if(!btn) return;
  function show(label,fn){
    btn.style.display='inline-flex';btn.textContent=label;
    btn.onclick=fn;
  }
  window.addEventListener('beforeinstallprompt',function(e){
    e.preventDefault();show('Install app',function(){e.prompt();});
  });
  var ios=/iphone|ipad|ipod/i.test(navigator.userAgent);
  var standalone=window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone;
  if(ios && !standalone){
    show('Add to Home Screen',function(){
      alert('Tap Share, then "Add to Home Screen" to install FolioFrame.');
    });
  }
})();
</script>
"""
HINT_JS = """
<script>
/* "?" hints behave like tooltips (shared): hover/focus reveals on desktop,
   tap toggles on touch screens; delegated so it covers dynamic content. */
(function(){
  var canHover = window.matchMedia('(hover: hover)').matches;
  function popOf(b){ return b.parentElement.querySelector('.hint-pop'); }
  function hintOf(t){ return t&&t.closest?t.closest('.hint'):null; }
  function closeAll(except){
    Array.prototype.forEach.call(
      document.querySelectorAll('.hint[aria-expanded="true"]'), function(o){
        if(o===except) return;
        o.setAttribute('aria-expanded','false');
        var q=popOf(o); if(q) q.hidden=true;
      });
  }
  function open(b){
    closeAll(b);
    var q=popOf(b); if(!q) return;
    q.hidden=false;
    b.setAttribute('aria-expanded','true');
    /* keep the tooltip fully inside the viewport (e.g. narrow phones) */
    q.style.left=''; q.style.right=''; q.style.transform='';
    var r=q.getBoundingClientRect(), m=12, vw=window.innerWidth;
    if(r.left < m || r.right > vw - m){
      q.style.left='50%'; q.style.right='auto';
      q.style.transform='translateX(-50%)';
      r=q.getBoundingClientRect();
      var s=0;
      if(r.left < m) s=m-r.left; else if(r.right > vw-m) s=(vw-m)-r.right;
      if(s) q.style.transform='translateX(calc(-50% + '+s+'px))';
    }
  }
  function close(b){
    var q=popOf(b); if(q) q.hidden=true;
    b.setAttribute('aria-expanded','false');
  }
  if(canHover){
    document.addEventListener('mouseover',function(e){
      var b=hintOf(e.target); if(b) open(b);
    });
    document.addEventListener('mouseout',function(e){
      var b=hintOf(e.target); if(!b) return;
      var rt=e.relatedTarget;
      if(rt && b.parentElement.contains(rt)) return;
      close(b);
    });
    document.addEventListener('focusin',function(e){
      var b=hintOf(e.target); if(b) open(b);
    });
    document.addEventListener('focusout',function(e){
      var b=hintOf(e.target); if(b) close(b);
    });
  }
  document.addEventListener('click',function(e){
    var b=hintOf(e.target);
    if(!b){ closeAll(null); return; }
    if(!canHover){
      if(b.getAttribute('aria-expanded')==='true') close(b); else open(b);
    }
  });
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape') closeAll(null);
  });
})();
</script>
"""


def WELCOME_HTML():
    """Public welcome page: frosted-glass hero, GIS sign-in only."""
    return """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>FolioFrame</title>
""" + PWA_HEAD + THEME_CSS + """
#err{margin-top:10px}
</style>
<script src='https://accounts.google.com/gsi/client' async defer></script>
</head><body>
<div class='bg'><div class='blob b1'></div><div class='blob b2'></div>
<div class='blob b3'></div></div>
<main class='sheet sheet-wide'>
  <div class='card hero'>
    <img src='/static/icon-192.png' alt='FolioFrame'>
    <h1>FolioFrame</h1>
    <p class='tag'>Your memories, floating on glass.</p>
    <div id='gbtn'></div>
    <p id='err' class='err'></p>
    <p class='fine'>Takes about 30 seconds. We never see your Google password.<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About sign-in'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>Sign-in happens in Google’s own popup. FolioFrame only receives a basic profile token — never your password.</span></span><br>
    <span id='https-note' style='display:none'>Heads up: Google sign-in needs
    this page over HTTPS (or localhost).</span></p>
  </div>
  <div class='card'>
    <div class='feat'><div class='ic'>&#x1F5BC;</div><div>
      <b>You choose the photos</b>
      <span>Pick from Google Photos whenever you like — the frame shows them on its own.</span>
    </div></div>
    <div class='feat'><div class='ic'>&#x1F512;</div><div>
      <b>Private by design</b>
      <span>Read-only access. We never change, move, or delete your photos.</span>
    </div></div>
    <div class='feat'><div class='ic'>&#x1F4F1;</div><div>
      <b>Made for your home</b>
      <span>Installs like an app. Pair a frame with the code on its screen.</span>
    </div></div>
  </div>
  <div class='card installbar' id='installcard'>
    <div style='flex:1'><b>Install FolioFrame</b><br>
    <span class='muted'>Add it to your home screen for the full app feel.</span></div>
    <button class='btn btn-ghost btn-sm' id='installbtn' style='display:none'>Install app</button><span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About installing'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>Adds the FolioFrame console to your home screen so it opens like a native app.</span></span>
  </div>
  <div class='card' style='text-align:center'>
    <span class='muted'>Setting up a new frame?</span><br>
    <a class='btn btn-ghost btn-sm' href='/flash' style='margin-top:8px'>Flash firmware over USB</a>
    <p class='fine'>No login needed — install the firmware here first, then set up the frame as usual.</p>
  </div>
</main>
<script>
function showError(m){document.getElementById('err').textContent=m;}
function onGoogle(r){
  fetch('/api/auth/token',{method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id_token:r.credential})})
  .then(r=>r.json()).then(j=>{
    if(j.ok) location.href='/';
    else showError(j.error||'Sign-in failed. Please try again.');
  }).catch(()=>showError('Could not reach the server. Please try again.'));
}
function initGis(cid){
  if(!(window.google&&google.accounts&&google.accounts.id)){
    setTimeout(function(){initGis(cid);},200);return;
  }
  if(location.protocol!=='https:'&&location.hostname!=='localhost'
     &&location.hostname!=='127.0.0.1')
    document.getElementById('https-note').style.display='inline';
  google.accounts.id.initialize({client_id:cid,callback:onGoogle});
  google.accounts.id.renderButton(document.getElementById('gbtn'),
    {type:'standard',theme:'filled_black',size:'large',width:280});
}
(function(){
  var card=document.getElementById('installcard');
  function showInstall(){card.classList.add('show');}
  window.addEventListener('beforeinstallprompt',function(){showInstall();});
  var ios=/iphone|ipad|ipod/i.test(navigator.userAgent);
  var standalone=window.matchMedia('(display-mode: standalone)').matches
    || window.navigator.standalone;
  if(ios && !standalone) showInstall();
})();
window.addEventListener('load',function(){
  fetch('/api/config').then(r=>r.json()).then(c=>{
    var cid=c.google_client_id||'';
    if(!cid){showError('This server is not set up yet.');return;}
    initGis(cid);
  }).catch(()=>showError('Could not reach the server. Please try again.'));
});
</script>
""" + HINT_JS + SW_REGISTER + """</body></html>"""


def PHOTOS_HTML():
    """Photo picker page: thumbnail grid, e-ink preview panel, 3:4 editor.

    Thumbnails come from /api/photos (the user's Google Photos cache);
    clicking one opens the preview (original + simulated six-color e-ink);
    the editor's Apply POSTs the rendered 1200x1600 JPEG to
    /api/photos/<id>/edit, replacing the cached photo.
    """
    return """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>Photos - FolioFrame</title>
""" + PWA_HEAD + THEME_CSS + """
</head><body>
<div class='bg'><div class='blob b1'></div><div class='blob b2'></div>
<div class='blob b3'></div></div>
<header class='topbar'><div class='topbar-in'>
  <a class='brand' href='/' style='text-decoration:none;color:inherit'><img src='/static/icon-192.png' alt=''>FolioFrame</a>
  <a class='navlink' href='/'>Console</a>
  <span class='navlink' aria-current='page'>Photos</span>
  <span class='sp'></span>
  <button class='iconbtn' onclick='ffThemeToggle()' title='Toggle theme'
    aria-label='Toggle theme'>&#x1F315;</button>
</div></header>
<main class='sheet sheet-wide'>
  <div class='card'>
    <div class='photo-section-head'>
      <h2>Your photos</h2>
      <span id='photoCount'></span>
    </div>
    <p class='sub'>Tap a photo to preview it on simulated e-ink, or edit it for your frame.<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About the photo picker'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>These are the photos your frames draw from. Edits replace the photo here, so the frame picks up the edited version on its next rotation.</span></span></p>
    <div class='photo-grid' id='photoGrid' aria-label='Your photos'></div>
    <p class='photo-empty' id='photoEmpty' hidden></p>
  </div>
</main>
<div class='preview-shell' id='previewShell' aria-hidden='true'>
  <aside class='preview-panel' role='dialog' aria-modal='true' aria-labelledby='previewTitle'>
    <div class='preview-top'>
      <div><h2 id='previewTitle'>Frame preview</h2><p id='previewName'>Selected photo</p></div>
      <div class='preview-actions'>
        <button class='btn btn-ghost btn-sm' id='previewEdit' type='button'>Edit photo</button>
        <button class='iconbtn preview-close' id='previewClose' type='button' aria-label='Close preview'>&times;</button>
      </div>
    </div>
    <div class='preview-grid'>
      <figure class='preview-figure'>
        <figcaption class='preview-label'>Original <span>Source colors</span></figcaption>
        <div class='preview-media'><img id='previewOriginal' src='' alt='Original selected photo'></div>
      </figure>
      <figure class='preview-figure'>
        <figcaption class='preview-label'><span class='preview-label-main'>E-ink preview &mdash; simulated<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About the simulated e-ink preview'>?</button><span class='hint-pop hint-pop--below' role='tooltip' hidden>An approximation of how this photo will look on the frame's six-color e-paper display. Real e-paper shows softer colors and less fine detail than your phone or computer screen.</span></span></span><span>1200 &times; 1600 fit</span></figcaption>
        <div class='preview-media'>
          <canvas id='einkCanvas' width='360' height='480' aria-label='Simulated six-color e-ink rendering'></canvas>
          <div class='render-state' id='renderState' role='status' aria-live='polite'>Rendering preview&hellip;</div>
        </div>
      </figure>
    </div>
    <p class='preview-credit'>Preview only &mdash; a close approximation of the frame's six-color e-paper display.</p>
  </aside>
</div>
<div class='editor-shell' id='editorShell' aria-hidden='true'>
  <section class='editor-panel' role='dialog' aria-modal='true' aria-labelledby='editorTitle'>
    <div class='editor-head'>
      <div><h2 id='editorTitle'>Edit for your frame<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About editing photos for your frame'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>A final framing pass before a photo reaches your frame. Drag to reposition, use the sliders for zoom, brightness, and contrast, and rotate in 90&deg; steps &mdash; the 3:4 crop itself never changes, so the frame always fills edge to edge.</span></span></h2><p id='editorName'>Selected photo</p></div>
      <button class='iconbtn' id='editorClose' type='button' aria-label='Cancel and close editor'>&times;</button>
    </div>
    <div class='editor-layout'>
      <div>
        <div class='crop-stage' id='cropStage' aria-label='3 by 4 crop preview. Drag to reposition the photo.'>
          <canvas class='editor-canvas' id='editorCanvas' width='360' height='480' tabindex='0'></canvas>
          <div class='crop-frame' aria-hidden='true'><span class='frame-cols'></span></div>
          <span class='full-bleed-badge'>3:4 &middot; fills the whole frame<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About filling the whole frame'>?</button><span class='hint-pop hint-pop--left' role='tooltip' hidden>The frame's screen is 3:4, so your photo always fills it edge to edge &mdash; no black bars. Drag or zoom to reframe; the crop shape itself stays fixed.</span></span></span>
        </div>
      </div>
      <div class='editor-controls'>
        <p class='editor-help'>Drag the photo to reposition it. Zoom with the slider, mouse wheel, or a two-finger pinch. The crop stays fully covered automatically.</p>
        <div class='control-row'>
          <label for='zoomRange'>Zoom</label>
          <input class='editor-range' id='zoomRange' type='range' min='100' max='300' value='100' step='1'>
          <output class='control-value' id='zoomValue' for='zoomRange'>100%</output>
        </div>
        <div class='control-row'>
          <label for='brightnessRange'>Brightness</label>
          <input class='editor-range' id='brightnessRange' type='range' min='70' max='130' value='100' step='1'>
          <output class='control-value' id='brightnessValue' for='brightnessRange'>100%</output>
        </div>
        <div class='control-row'>
          <label for='contrastRange'>Contrast</label>
          <input class='editor-range' id='contrastRange' type='range' min='70' max='130' value='100' step='1'>
          <output class='control-value' id='contrastValue' for='contrastRange'>100%</output>
        </div>
        <div class='adjustment-reset-row'>
          <button class='btn btn-ghost btn-sm' id='resetAdjustments' type='button'>Reset brightness &amp; contrast</button>
        </div>
        <div class='rotate-row'>
          <button class='btn btn-ghost btn-sm' id='rotateButton' type='button' aria-label='Rotate photo 90 degrees clockwise'>&#x21BB; Rotate 90&deg;</button>
          <span id='rotationValue'>0&deg;</span>
        </div>
      </div>
    </div>
    <div class='editor-actions'>
      <button class='btn btn-ghost' id='editorCancel' type='button'>Cancel</button>
      <button class='btn btn-primary' id='editorApply' type='button'>Apply edit</button>
    </div>
    <p class='editor-status' id='editorStatus' role='status'></p>
  </section>
</div>
<script src='/static/photos.js?v=""" + _static_ver("photos.js") + """'></script>
""" + SW_REGISTER + """</body></html>"""


def _flash_page(available, version, versions):
    """Public firmware-flash page (no login): Web Serial via esp-web-tools.

    30/70 split: controls on the left, the embedded flash console on the
    right. The <ewt-install-dialog> element is instantiated directly so the
    whole flow (port pick, erase, write, verify, logs) stays in the page
    instead of a popup. `versions` is the published firmware list, newest
    first; the picker swaps the manifest the dialog flashes.
    """
    import os as _os
    body = ""
    if available:
        opts = "".join(
            f"<option value='{v}'{' selected' if v == version else ''}>"
            f"{v}{' (latest)' if v == version else ''}</option>"
            for v in versions
        )
        picker = (f"<label class='fld'>Firmware version<br><select id='fwver'>"
                  f"{opts}</select></label>" if len(versions) > 1 else
                  f"<p class='muted'>Firmware <b>{version}</b> for ESP32-S3</p>")
        parts_rows = "".join(
            f"<tr><td class='mono'>{n}</td>"
            f"<td class='mono'>0x{o:X}</td>"
            f"<td class='num'>{_os.path.getsize(_os.path.join(FW_DIR, n if n != 'firmware.bin' else 'firmware.bin')) // 1024} KB</td></tr>"
            for n, o in FLASH_PARTS
        )
        body = f"""
  <div class='flash-split'>
    <div class='flash-left'>
      <div class='card'>
        <h3>Steps</h3>
        <div class='feat'><div class='ic'>&#x1F50C;</div><div>
          <b>Plug in the frame</b>
          <span>Connect the EE02 driver board to this computer with USB-C.</span>
        </div></div>
        <div class='feat'><div class='ic'>&#x1F310;</div><div>
          <b>Use a compatible browser</b>
          <span>Chrome, Edge, or Opera on a computer (needs Web Serial).</span>
        </div></div>
        <div class='feat'><div class='ic'>&#x2699;&#xFE0F;</div><div>
          <b>Flash, then configure</b>
          <span>After flashing, the frame's Wi-Fi portal lets you point it at
          <i>any</i> FolioFrame server — this one or your own.</span>
        </div></div>
      </div>
      <div class='card'>
        <h3>Firmware</h3>
        {picker}
        <button class='btn btn-primary' id='flash-go'>Connect &amp; flash</button>
        <p class='fine'>Your browser will ask which serial port to use —
        pick the one for the frame. The flash runs in the console
        on the right.</p>
      </div>
    </div>
    <div class='flash-right'>
      <div class='card'>
        <h3>Flash console</h3>
        <div id='console-wrap'>
          <p class='muted' id='console-idle'>Idle — pick a version and hit
          <b>Connect &amp; flash</b>. Port selection, erase, write, verify
          and the log all appear here.</p>
        </div>
      </div>
      <div class='card'>
        <h3>Image details</h3>
        <table class='parts'><tr><th>File</th><th>Offset</th><th>Size</th></tr>
        {parts_rows}</table>
        <p class='fine'>Chip: ESP32-S3 · <span class='mono'>firmware.bin</span>
        is also served for over-the-air updates.</p>
      </div>
    </div>
  </div>
  <script type='module'>
  import('/static/esp-web-tools/install-dialog.js');
  (function(){{
    var go=document.getElementById('flash-go');
    var sel=document.getElementById('fwver');
    var wrap=document.getElementById('console-wrap');
    function manifestUrl(){{
      var v=sel?sel.value:'{version}';
      return '/flash/manifest.json?version='+encodeURIComponent(v);
    }}
    if(sel) sel.addEventListener('change',function(){{
      // If a dialog is already open, swap its manifest for the next run.
      var dlg=wrap.querySelector('ewt-install-dialog');
      if(dlg) dlg.manifestPath=manifestUrl();
    }});
    go.addEventListener('click',async function(){{
      if(!('serial' in navigator)){{
        wrap.innerHTML='<p class=\"err\">Web Serial is not available. Use Chrome, Edge or Opera on a computer (HTTPS required).</p>';
        return;
      }}
      var port;
      try{{ port=await navigator.serial.requestPort(); }}
      catch(e){{ return; }}  // user cancelled the port picker
      try{{ await port.open({{baudRate:115200,bufferSize:8192}}); }}
      catch(e){{
        wrap.innerHTML='<p class=\"err\">Could not open the serial port: '+e.message+'</p>';
        return;
      }}
      wrap.innerHTML='';
      var dlg=document.createElement('ewt-install-dialog');
      dlg.port=port;
      dlg.manifestPath=manifestUrl();
      dlg.addEventListener('closed',function(){{
        try{{port.close();}}catch(e){{}}
      }},{{once:true}});
      wrap.appendChild(dlg);
    }});
  }})();
  </script>"""
    else:
        body = """
  <div class='card' style='text-align:center'>
    <p><b>No firmware published yet.</b></p>
    <p class='muted'>The admin hasn't published the flash binaries on this
    server. Ask them to drop the four <span class='mono'>.bin</span> files
    into <span class='mono'>server/firmware/</span> and redeploy.</p>
  </div>"""
    return ("""<html><head><meta name='viewport'
content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>Flash FolioFrame firmware</title>
""" + PWA_HEAD + THEME_CSS + """
<style>
.mono{font-family:ui-monospace,monospace;font-size:.9em}
esp-web-install-button{--esp-tools-button-color:var(--accent);
  --esp-tools-button-text-color:#fff}
/* Flash page 30/70 split */
.flash-split{display:flex;gap:16px;align-items:flex-start}
.flash-left{flex:0 0 30%;min-width:0;display:flex;flex-direction:column;gap:16px}
.flash-right{flex:1;min-width:0;display:flex;flex-direction:column;gap:16px}
.flash-left .card,.flash-right .card{margin:0}
.flash-split h3{margin:0 0 12px;font-size:1.05em}
.fld{display:block;margin:0 0 12px;font-size:.9em}
.fld select{margin-top:6px;max-width:100%;padding:8px 10px;border-radius:10px;
  border:1px solid rgba(255,255,255,.18);background:rgba(255,255,255,.06);
  color:inherit;font-size:1em}
#console-wrap{min-height:300px}
#console-wrap ewt-install-dialog{display:block;width:100%;border-radius:14px;
  overflow:hidden;color-scheme:dark;
  /* Dark-theme the Material install dialog so it reads as part of the
     page instead of a popup (tokens pierce its shadow DOM). */
  --md-sys-color-surface:#141a30;
  --md-sys-color-on-surface:#f4f6ff;
  --md-sys-color-on-surface-variant:rgba(240,244,255,.68);
  --md-sys-color-primary:var(--accent);
  --md-sys-color-on-primary:#ffffff;
  --md-sys-color-primary-container:rgba(10,132,255,.30);
  --md-sys-color-on-primary-container:#f4f6ff;
  --md-sys-color-secondary-container:rgba(10,132,255,.18);
  --md-sys-color-on-secondary-container:#f4f6ff;
  --md-sys-color-tertiary:var(--secondary);
  --md-sys-color-tertiary-container:rgba(133,152,121,.30);
  --md-sys-color-surface-container:rgba(255,255,255,.06);
  --md-sys-color-surface-container-highest:rgba(255,255,255,.10);
  --md-sys-color-error:#ff453a;
  --md-sys-color-on-error-container:#ffd7d2;
  --md-sys-color-shadow:#000}
.parts{width:100%;border-collapse:collapse;font-size:.85em}
.parts th,.parts td{padding:6px 8px;text-align:left;
  border-bottom:1px solid rgba(255,255,255,.08)}
.parts th{opacity:.7;font-weight:600}
.parts td.num{text-align:right}
.err{color:var(--error)}
@media(max-width:900px){
  .flash-split{flex-direction:column}
  .flash-left{flex:none;width:100%}
}
</style>
</head><body>
<div class='bg'><div class='blob b1'></div><div class='blob b2'></div>
<div class='blob b3'></div></div>
<main class='sheet sheet-wide'>
  <div class='topbar'><div class='topbar-in'>
    <span class='brand'><img src='/static/icon-192.png' alt=''>FolioFrame</span>
    <span class='sp'></span>
    <button class='iconbtn' onclick='ffThemeToggle()' title='Toggle theme'
      aria-label='Toggle theme'>&#x1F315;</button>
    <a class='btn btn-ghost btn-sm' href='/'>Home</a>
  </div></div>
  <div class='card hero'>
    <h1>Flash the frame<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About flashing'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>Installs FolioFrame firmware on the EE02 driver board over USB, right from this page. No login needed.</span></span></h1>
    <p class='tag'>Install FolioFrame firmware over USB, right from
    this page. No login needed.</p>
  </div>""" + body + """
</main>
""" + HINT_JS + SW_REGISTER + """</body></html>""")


CONSOLE_HTML = """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>FolioFrame</title>
""" + PWA_HEAD + THEME_CSS + """
</head><body>
<div class='bg'><div class='blob b1'></div><div class='blob b2'></div>
<div class='blob b3'></div></div>
<header class='topbar'><div class='topbar-in'>
  <span class='brand'><img src='/static/icon-192.png' alt=''>FolioFrame</span>
  <a class='navlink' href='/photos'>Photos</a>
  <span class='sp'></span>
  <button class='iconbtn' onclick='ffThemeToggle()' title='Toggle theme'
    aria-label='Toggle theme'>&#x1F315;</button>
  <button class='btn btn-ghost btn-sm' id='installbtn' style='display:none'>Install</button>
  <span class='avatar' id='avatar' title=''>?</span>
  <button class='iconbtn' onclick='logout()' title='Sign out'
    aria-label='Sign out'>&#x23FB;</button>
</div></header>
<main class='sheet sheet-wide'>
  <div class='card'>
    <h2>My uploads<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About uploads'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>Photos you upload here are stored on your server and can be shown on your frames. No frame needs to be paired first.</span></span></h2>
    <p class='sub'>Your personal photo library on this server.</p>
    <div id='uploads' class='upgrid'><p class='muted'>Loading&hellip;</p></div>
    <form onsubmit='return upUpload(event)'>
      <input type='file' name='photo' accept='image/*' multiple required
        aria-label='Photos to upload'>
      <button class='btn btn-primary btn-sm'>Upload photos</button>
    </form>
    <p class='msg' id='uploads-msg'></p>
  </div>
  <div class='card' id='photos-card'>
    <h2>Google Photos<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About Google Photos'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>Your frame’s photo library. Connect once, then pick the photos you love.</span></span></h2>
    <p class='sub' id='photos-sub'>Your frame's photo library.</p>
    <div id='photos'><p class='muted'>Loading&hellip;</p></div>
  </div>
  <div class='card'>
    <h2>Photo source<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About photo source'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>What your frames show right now. Switch sources anytime — frames pick it up at their next wake.</span></span></h2>
    <p class='sub'>What your frames show right now.</p>
    <div class='seg' id='src' role='tablist' aria-label='Photo source'></div>
    <div class='btnrow'>
      <button class='btn btn-ghost btn-sm' onclick='nextFrame()'>Show next photo now</button>
    </div>
    <p class='msg' id='src-msg'></p>
  </div>
  <div class='card'>
    <h2>Frames</h2>
    <p class='sub'>Devices paired to your account.</p>
    <div id='devices'><p class='muted'>Loading&hellip;</p></div>
  </div>
  <div class='card'>
    <h2>Account</h2>
    <div class='kv'><span class='k'>Signed in as</span><b id='who'></b></div>
    <div class='btnrow'>
      <button class='btn btn-ghost btn-sm' onclick='logout()'>Sign out</button>
    </div>
  </div>
</main>
<script>
let CSRF='';
const SRC_NAMES={dashboard:'Daily dashboard',folder:'Photo folder',uploads:'My uploads',
google_photos:'Google Photos',picsum:'Sample photos',url:'Web image'};
function srcName(n){return SRC_NAMES[n]||n;}
async function api(m,u,b,form){
  const o={method:m,headers:{'X-CSRF-Token':CSRF}};
  if(form){o.body=b;}
  else if(b){o.headers['Content-Type']='application/json';o.body=JSON.stringify(b);}
  const r=await fetch(u,o);return r.json().catch(()=>({ok:false,error:'Server unreachable'}));
}
function esc(s){return String(s??'').replace(/[&<>"']/g,
  c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function init(){
  const s=await (await fetch('/api/session')).json();
  if(!s.ok){location.href='/';return;}
  CSRF=s.csrf;
  const a=await (await fetch('/api/account')).json();
  document.getElementById('who').textContent=a.email||'';
  const av=document.getElementById('avatar');
  av.textContent=(a.email||'?').trim().charAt(0).toUpperCase()||'?';
  av.title=a.email||'';
  renderDevices();renderSources(a);renderPhotos();renderUploads();
}
/* ---------- Google Photos ---------- */
async function renderPhotos(){
  const g=await (await fetch('/api/gphotos/status')).json();
  const el=document.getElementById('photos');
  const sub=document.getElementById('photos-sub');
  if(!g.connected){
    sub.textContent='Connect once, then pick the photos you love.';
    el.innerHTML=`
      <p><span class='pill'><span class='dot'></span>Not connected</span></p>
      <div class='feat'><div class='ic'>&#x1F512;</div><div>
        <b>Read-only</b><span>We never change, move, or delete your photos.</span>
      </div></div>
      <div class='feat'><div class='ic'>&#x1F5BC;</div><div>
        <b>You choose</b><span>You pick exactly which photos we can see.</span>
      </div></div>
      <div class='btnrow'>
        <a class='btn btn-primary' href='/api/gphotos/connect?origin=${encodeURIComponent(location.origin)}'>Connect Google Photos</a>
      </div>
      <p class='muted'>You approve access on Google's own screen — nothing to copy or paste.</p>
      <p class='msg' id='photos-msg'></p>`;
  }else{
    let st='';
    if(g.picking)
      st=`<p class='msg'>Picker open — <a style='color:#fff' href='${esc(g.picker_uri)}' target='_blank' rel='noopener'>continue choosing photos</a>, then come back here.</p>`;
    else if(g.pick_status==='error')
      st=`<p class='msg err'>Couldn't finish picking: ${esc(g.pick_error)} Please try again.</p>`;
    sub.textContent='Connected — your picks live on this server.';
    el.innerHTML=`
      <p><span class='pill on'><span class='dot'></span>Connected</span>
      <span class='muted'> &middot; ${g.cached} photo${g.cached==1?'':'s'} ready for your frame</span></p>
      ${st}
      <div class='btnrow'>
        <button class='btn btn-primary' onclick='gpick()'>Pick more photos</button>
        <button class='btn btn-ghost' onclick='gdisc()'>Disconnect</button>
      </div>
      <p class='msg' id='photos-msg'></p>`;
    if(g.picking) pollPick();
  }
}
async function gpick(){
  const msg=document.getElementById('photos-msg');
  msg.className='msg';msg.textContent='Opening the photo picker…';
  const w=open('','_blank');
  const r=await api('POST','/api/gphotos/pick');
  if(r.ok&&r.picker_uri){
    if(w){w.location.href=r.picker_uri;}else{open(r.picker_uri,'_blank');}
    renderPhotos();
  }else{
    if(w){w.close();}
    msg.className='msg err';
    msg.textContent="Couldn't open the picker: "+(r.error||'unknown error')+'. Please try again.';
  }
}
async function pollPick(){
  for(let i=0;i<48;i++){
    await new Promise(r=>setTimeout(r,5000));
    const g=await (await fetch('/api/gphotos/status')).json();
    if(!g.picking){renderPhotos();return;}
  }
  renderPhotos();
}
async function gdisc(){
  if(!confirm('Disconnect Google Photos? Your chosen photos stay on this server until you pick again.'))return;
  await api('POST','/api/gphotos/disconnect');renderPhotos();
}
/* ---------- uploads ---------- */
async function renderUploads(){
  const el=document.getElementById('uploads');
  const r=await (await fetch('/api/uploads')).json();
  if(!r.ok||!r.photos.length){
    el.innerHTML=`<p class='muted'>No uploads yet — pick some photos below.</p>`;
    return;
  }
  el.innerHTML=r.photos.map(p=>`
    <div class='upitem'>
      <img src='${esc(p.url)}' alt='' loading='lazy'>
      <button class='updel' onclick="upDelete('${esc(p.name)}')"
        aria-label='Delete photo'>&times;</button>
    </div>`).join('');
}
async function upUpload(e){
  e.preventDefault();
  const m=document.getElementById('uploads-msg');
  m.className='msg';m.textContent='Uploading…';
  const r=await api('POST','/api/uploads',new FormData(e.target),true);
  if(r.ok){
    m.className='msg ok';
    m.textContent=`Uploaded ${r.count} photo${r.count==1?'':'s'}.`;
    e.target.reset();renderUploads();
  }else{
    m.className='msg err';
    m.textContent='Upload failed: '+(r.error||'unknown error');
  }
  return false;
}
async function upDelete(name){
  if(!confirm('Delete this photo?'))return;
  const r=await api('DELETE','/api/uploads/'+encodeURIComponent(name));
  const m=document.getElementById('uploads-msg');
  if(r.ok){m.className='msg ok';m.textContent='Deleted.';renderUploads();}
  else{m.className='msg err';m.textContent='Delete failed.';}
}
/* ---------- sources ---------- */
async function renderSources(a){
  document.getElementById('src').innerHTML=
    a.sources.map(n=>`<button role='tab' aria-selected='${n===a.source}'
      class='${n===a.source?'sel':''}'
      ${n===a.source?'disabled':''}
      onclick="setSrc('${n}')">${srcName(n)}</button>`).join('');
}
async function setSrc(n){
  const r=await api('POST','/api/source',{name:n});
  const m=document.getElementById('src-msg');
  if(!r.ok){m.className='msg err';m.textContent='Could not switch: '+(r.error||'unknown error');return;}
  init();
}
async function nextFrame(){
  const r=await api('POST','/api/next');
  const m=document.getElementById('src-msg');
  m.className='msg '+(r.ok?'ok':'err');
  m.textContent=r.ok?'Rotating now — your frames update at their next wake.':'Could not rotate: '+(r.error||'unknown error');
}
/* ---------- devices ---------- */
async function renderDevices(){
  const d=await (await fetch('/api/devices')).json();
  const el=document.getElementById('devices');
  if(!d.devices.length){
    el.innerHTML=`<p><b>No frames paired yet.</b></p>
    <p class='muted'>When your frame arrives, pair it with the code shown on its screen.</p>
    <div class='btnrow'><a class='btn btn-primary' href='/claim'>Pair a frame</a></div>`;
    return;
  }
  const latestBuild=d.latest_build||0, latestFw=d.latest_fw||'';
  el.innerHTML=d.devices.map(dev=>{
    const behind=dev.fw_build!=null&&latestBuild&&dev.fw_build<latestBuild;
    const fwBadge=behind?` <span class='pill'><span class='dot'></span>Update available: ${esc(latestFw)}</span>`:'';
    return `
    <div class='dev'>
      <span class='nm'>${esc(dev.name||'Frame')}</span><br>
      <span class='meta'>${esc(dev.device_id)}<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About the device ID'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>The frame’s unique ID, also shown on its setup screen.</span></span></span><br>
      <span class='meta'>Last seen: ${dev.last_seen?new Date(dev.last_seen*1000).toLocaleString():'never'}
      &middot; Battery: ${esc(dev.battery_pct??'&mdash;')}% &middot; Firmware: ${esc(dev.fw??'&mdash;')}${fwBadge}<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About frame status'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>When the frame last checked in, its battery level, and the installed firmware version.</span></span></span>
      ${dev.override?'<p><b>&#x1F4CC; Pinned photo active</b> <button class="btn btn-ghost btn-sm" onclick="clearOv(\\''+dev.device_id+'\\')">Clear</button></p>':''}
      <img src='/api/devices/${dev.device_id}/preview' alt='What this frame is showing now' loading='lazy'>
      <form onsubmit='return upload(event,"${dev.device_id}")'>
        <input type='file' name='photo' accept='image/*' required aria-label='Photo to push'>
        <button class='btn btn-ghost btn-sm'>Push photo to frame</button>
      </form>
      <p class='muted'>Pushing pins the photo immediately; the frame shows it at its next wake.</p>
      <div class='btnrow'>
        <button class='btn btn-ghost btn-sm' onclick='renameDev("${dev.device_id}")'>Rename</button>
        <button class='btn btn-ghost btn-sm' onclick='unpair("${dev.device_id}")'>Unpair</button>
      </div>
    </div>`;
  }).join('')+`<p class='msg' id='dev-msg'></p>
    <div class='btnrow'><a class='btn btn-ghost btn-sm' href='/claim'>Pair another frame</a></div>`;
}
function devMsg(msg,isErr){
  const m=document.getElementById('dev-msg');if(!m)return;
  m.className='msg '+(isErr?'err':'ok');m.textContent=msg;
}
async function upload(e,id){
  e.preventDefault();
  const r=await api('POST','/api/devices/'+id+'/photos/upload',new FormData(e.target),true);
  devMsg(r.ok?'Pushed — shows on the frame at its next wake.':'Push failed: '+(r.error||'unknown error'),!r.ok);
  init();return false;
}
async function clearOv(id){
  if(!confirm('Clear the pinned photo and resume the normal source?'))return;
  const r=await api('DELETE','/api/devices/'+id+'/photos/override');
  devMsg(r.ok?'Pinned photo cleared.':'Could not clear: '+(r.error||'unknown error'),!r.ok);
  init();
}
async function unpair(id){
  if(!confirm('Unpair this frame? Its access is revoked immediately.'))return;
  const r=await api('DELETE','/api/devices/'+id);
  devMsg(r.ok?'Frame unpaired.':'Could not unpair: '+(r.error||'unknown error'),!r.ok);
  init();
}
async function renameDev(id){
  const n=prompt('Name this frame:', '');
  if(n==null||!n.trim())return;
  const r=await api('PATCH','/api/devices/'+id,{name:n.trim()});
  devMsg(r.ok?'Renamed.':'Could not rename: '+(r.error||'unknown error'),!r.ok);
  init();
}
async function logout(){await fetch('/api/auth/logout',{method:'POST'});location.href='/';}
init();
</script>
""" + HINT_JS + SW_REGISTER + """</body></html>"""


CLAIM_HTML = """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1,viewport-fit=cover'>
<title>Pair a frame &middot; FolioFrame</title>
""" + PWA_HEAD + THEME_CSS + """
form .btn{width:100%;margin-top:14px}
</style>
</head><body>
<div class='bg'><div class='blob b1'></div><div class='blob b2'></div>
<div class='blob b3'></div></div>
<main class='sheet' style='max-width:480px'>
  <div class='card' style='margin-top:8vh'>
   <div class='card-body text-center'>
    <img src='/static/icon-192.png' alt='' style='width:64px;height:64px;border-radius:18px'>
    <h2 class='card-title mt-2'>Pair a frame</h2>
    <p class='sub'>Enter the 8-character code shown on the frame's screen.<span class='hint-wrap'><button class='hint' type='button' aria-expanded='false' aria-label='About the pairing code'>?</button><span class='hint-pop hint-pop--below hint-pop--left' role='tooltip' hidden>The code appears on the frame’s screen after it connects to Wi-Fi. It expires after a few minutes.</span></span></p>
    <form onsubmit='return pair(event)'>
      <input id='code' class='form-control code' placeholder='XXXX-XXXX' autocomplete='off'
        autocapitalize='characters' maxlength='9' aria-label='Pairing code'>
      <button class='btn btn-primary w-100 mt-3'>Pair frame</button>
    </form>
    <p class='msg' id='msg'></p>
   </div>
  </div>
</main>
<script>
let CSRF='';
fetch('/api/session').then(r=>r.json()).then(s=>{CSRF=s.csrf||'';});
async function pair(e){
  e.preventDefault();
  const code=document.getElementById('code').value.trim();
  const r=await (await fetch('/api/devices/claim',{method:'POST',
    headers:{'Content-Type':'application/json','X-CSRF-Token':CSRF},
    body:JSON.stringify({code})})).json();
  document.getElementById('msg').textContent=
    r.ok?('Paired: '+(r.name||r.device_id)):('Error: '+(r.error||'unknown error'));
  document.getElementById('msg').className='msg '+(r.ok?'ok':'err');
  if(r.ok){
    // Redirect to home after successful pairing
    setTimeout(function(){ window.location.href='/'; }, 1500);
  }
  return false;
}
</script>
""" + HINT_JS + SW_REGISTER + """</body></html>"""


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
    print(f"SpectraFrame server v2.2 on :{port} (frame {W}x{H})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
