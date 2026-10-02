#!/usr/bin/env python3
"""SpectraFrame companion server.

Implements PROTOCOL.md v2:
  Human (Google sign-in session):
    GET  /login, /claim, /               console pages
    POST /api/auth/google               {id_token} -> session cookie
    GET  /api/session, /api/devices     session info + my devices
    POST /api/devices/claim             {code} claim a device to my account
    PATCH/DELETE /api/devices/{id}      rename / unpair (revokes token)
    POST /api/devices/{id}/photos/upload  multipart -> pinned override
    DELETE /api/devices/{id}/photos/override  clear override
    GET  /api/devices/{id}/preview      PNG of what the device shows
  Device (Authorization: Bearer <token>):
    POST /v1/device/register            {device_id,...} -> claim code
    POST /v1/device/claim               {device_id, claim_code} poll
    GET  /v1/device/frame               packed 4bpp frame, ETag + 304
    POST /v1/device/status              heartbeat
    POST /v1/device/unpair              device-initiated unpair
    GET  /v1/device/ota/version, /v1/device/ota/firmware.bin

Security: no anonymous access to any frame, photo, or device control.
Config: server/config.json (created with defaults on first run).
State:  server/state.json (rotation history) + server/data/registry.json
        (users/devices/sessions, 0600).
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
from sources.google_photos import (GPhotosController, PickerClient, PickFlow,
                                   default_cache_dir)
from auth import AuthManager, AuthError, SESSION_COOKIE
from devices import DeviceRegistry, AlreadyPaired, BadClaim, RateLimiter
from store import JsonStore

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
        self.state = {"history": {}, "last_rotation": 0}
        if os.path.exists(st_path):
            with open(st_path) as f:
                self.state.update(json.load(f))
        self._state_path = st_path
        self.lock = threading.Lock()
        self.store = JsonStore(os.path.join(self.data_dir, "registry.json"))
        self.auth = AuthManager(self.store, self.cfg)
        self.devices = DeviceRegistry(self.store)
        self.ratelimit = RateLimiter()
        self.source = self._make_source(self.cfg.get("source", "picsum"))
        self.gphotos = GPhotosController(self.cfg, self.cfg.get("port", 8765))
        self.frame = None
        self.etag = None
        self.preview = None
        self.last_error = ""
        self.build = "1"
        self.rotate(force=True)

    def _make_source(self, name):
        cls = SOURCES.get(name)
        if not cls:
            raise ValueError(f"unknown source {name}")
        return cls(self.cfg.get(name, {}))

    def _save_state(self):
        tmp = self._state_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, self._state_path)

    def _device_dir(self, device_id):
        d = os.path.join(self.data_dir, "devices", device_id)
        os.makedirs(d, exist_ok=True)
        return d

    def switch_source(self, name):
        with self.lock:
            self.source = self._make_source(name)
            self.cfg["source"] = name
            with open(CONFIG_PATH, "w") as f:
                json.dump(self.cfg, f, indent=2)
        self.rotate(force=True)

    def gphotos_pick(self):
        """Create a picker session and import in the background."""
        gp = self.gphotos
        if not gp.oauth.connected:
            raise RuntimeError("Google Photos not connected")
        client = PickerClient(gp.oauth)
        session = client.create_session()
        gp.pick_state = {"session_id": session["id"],
                         "picker_uri": session["pickerUri"],
                         "status": "waiting", "count": 0, "error": ""}

        def run():
            try:
                n = PickFlow(client, default_cache_dir()).run(session["id"])
                gp.pick_state.update(status="done", count=n)
            except Exception as e:
                gp.pick_state.update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()
        return gp.pick_state["picker_uri"]

    def rotate(self, force=False):
        with self.lock:
            name = self.source.name
            hist = self.state["history"].get(name, [])
            try:
                item = self.source.next_id(hist)
                if item is None:
                    self.last_error = f"source {name}: no items"
                    return False
                img = self.source.load(item)
                frame = pipeline.process_image(
                    img, W, H, self.cfg.get("dither", "floyd"))
                self.frame = frame
                self.etag = pipeline.frame_etag(frame)
                self.preview = pipeline.preview_png(frame, W, H)
                hist.append(item)
                self.state["history"][name] = hist[-200:]
                self.state["last_rotation"] = int(time.time())
                self.last_error = ""
                self._save_state()
                print(f"rotated: {name}/{item} etag={self.etag}")
                return True
            except Exception as e:  # keep serving the old frame
                self.last_error = f"{name}: {e}"
                print("rotate failed:", self.last_error)
                return False

    def tick(self):
        """Background rotation tick: interval + quiet hours."""
        now = time.localtime()
        now_min = now.tm_hour * 60 + now.tm_min
        if in_quiet(now_min, self.cfg.get("quiet_start", "22:00"),
                    self.cfg.get("quiet_end", "07:00")):
            return
        interval = self.cfg.get("rotation_minutes", 60) * 60
        if time.time() - self.state["last_rotation"] >= interval:
            self.rotate()

    def device_frame(self, dev):
        """(frame_bytes, etag): pinned override wins, else global rotation."""
        etag = dev.get("override_etag")
        if etag:
            fp = os.path.join(self._device_dir(dev["device_id"]), "override.frame")
            if os.path.exists(fp):
                with open(fp, "rb") as f:
                    return f.read(), etag
        return self.frame, self.etag

    def device_preview(self, dev):
        etag = dev.get("override_etag")
        if etag:
            pp = os.path.join(self._device_dir(dev["device_id"]), "override.png")
            if os.path.exists(pp):
                with open(pp, "rb") as f:
                    return f.read()
        return self.preview

    def set_override(self, device_id, img):
        """Pin an uploaded PIL image as this device's frame. Returns etag."""
        frame = pipeline.process_image(img, W, H,
                                       self.cfg.get("dither", "floyd"))
        etag = pipeline.frame_etag(frame)
        d = self._device_dir(device_id)
        with open(os.path.join(d, "override.frame"), "wb") as f:
            f.write(frame)
        with open(os.path.join(d, "override.png"), "wb") as f:
            f.write(pipeline.preview_png(frame, W, H))
        return etag

    def clear_override_files(self, device_id):
        d = os.path.join(self.data_dir, "devices", device_id)
        for name in ("override.frame", "override.png"):
            p = os.path.join(d, name)
            if os.path.exists(p):
                os.remove(p)

    def describe(self):
        return {
            "source": self.source.describe(),
            "sources": sorted(SOURCES),
            "rotation_minutes": self.cfg.get("rotation_minutes"),
            "last_rotation": self.state["last_rotation"],
            "etag": self.etag,
            "last_error": self.last_error,
            "build": self.build,
        }


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

        if p == "/login":
            self._send(200, "text/html", LOGIN_HTML(
                APP.auth.client_id).encode())
            return

        if p == "/claim":
            if not self._human()[1]:
                self._redirect("/login")
                return
            self._send(200, "text/html", CLAIM_HTML.encode())
            return

        if p == "/":
            if not self._human()[1]:
                self._redirect("/login")
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
            if not self._require_human():
                return
            self._json(200, APP.describe())
            return

        if p == "/api/gphotos/connect":
            if not self._require_human():
                return
            gp = APP.gphotos
            if not gp.configured:
                html = """<html><body><h2>Google Photos setup needed</h2>
<p>Add your OAuth client to <code>server/config.json</code>:</p>
<pre>"google_photos": {
  "client_id": "...apps.googleusercontent.com",
  "client_secret": "..."
}</pre>
<p>See <code>docs/GOOGLE_PHOTOS.md</code> for the Cloud Console steps,
then restart the server and click Connect again.</p></body></html>"""
                self._send(200, "text/html", html.encode())
            else:
                self.send_response(302)
                self.send_header(
                    "Location", gp.oauth.auth_url(gp.new_state()))
                self.end_headers()
            return

        if p == "/api/gphotos/callback":
            if not self._require_human():
                return
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code, state = q.get("code", [""])[0], q.get("state", [""])[0]
            gp = APP.gphotos
            if not code or not gp.valid_state(state):
                self._send(400, "text/plain", b"bad oauth response")
            else:
                try:
                    gp.oauth.exchange_code(code)
                    self._redirect("/")
                except Exception as e:
                    self._send(500, "text/plain",
                                f"connect failed: {e}".encode())
            return

        if p == "/api/gphotos/status":
            if not self._require_human():
                return
            gp = APP.gphotos
            ps = gp.pick_state or {}
            self._json(200, {
                "configured": gp.configured,
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

        if p == "/api/auth/google":
            data = self._read_json()
            if data is None:
                self._json(400, {"ok": False, "error": "bad json"})
                return
            try:
                sub, email, name = APP.auth.verify_google_token(
                    data.get("id_token", ""))
            except AuthError as e:
                self._json(401, {"ok": False, "error": str(e)})
                return
            APP.store.put("users", sub, {"email": email, "name": name,
                                         "last_login": int(time.time())})
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

        if p == "/api/gphotos/pick":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            try:
                uri = APP.gphotos_pick()
                self._json(200, {"ok": True, "picker_uri": uri})
            except Exception as e:
                self._json(400, {"ok": False, "error": str(e)})
            return

        if p == "/api/gphotos/disconnect":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            APP.gphotos.oauth.disconnect()
            self._json(200, {"ok": True})
            return

        if p == "/api/next":
            got = self._require_human()
            if not got or not self._require_csrf(got[1]):
                return
            ok = APP.rotate(force=True)
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
                APP.switch_source(data.get("name", ""))
                self._json(200, {"ok": True})
            except ValueError as e:
                self._json(400, {"ok": False, "error": str(e)})
            return

        self.send_response(404)
        self.end_headers()

    # ---- PATCH / DELETE ------------------------------------------------
    def do_PATCH(self):
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

def LOGIN_HTML(client_id):
    return f"""<html><head><meta name='viewport'
content='width=device-width,initial-scale=1'><title>SpectraFrame login</title>
</head><body style='font-family:sans-serif;max-width:480px;margin:40px auto'>
<h2>SpectraFrame</h2><p>Sign in with your Google account to manage devices.</p>
<script src="https://accounts.google.com/gsi/client" async defer></script>
<div id="g_id_onload" data-client_id="{client_id}"
     data-callback="onGoogle" data-auto_prompt="false"></div>
<div class="g_id_signin" data-type="standard"></div>
<p id="err" style="color:red"></p>
<script>
function onGoogle(r){{
  fetch('/api/auth/google',{{method:'POST',
    headers:{{'Content-Type':'application/json'}},
    body:JSON.stringify({{id_token:r.credential}})}})
  .then(r=>r.json()).then(j=>{{
    if(j.ok) location.href='/'; else document.getElementById('err').textContent=j.error;
  }});
}}
</script></body></html>"""


CONSOLE_HTML = """<html><head><meta name='viewport'
content='width=device-width,initial-scale=1'><title>SpectraFrame</title>
</head><body style='font-family:sans-serif;max-width:640px;margin:20px auto'>
<h2>SpectraFrame console</h2>
<p><span id='who'></span> · <a href='/claim'>Pair a device</a> ·
<button onclick='logout()'>Sign out</button></p>
<div id='devices'>loading…</div>
<h3>Server source</h3>
<div id='srv'></div>
<script>
let CSRF='';
async function api(m,u,b,form){
  const o={method:m,headers:{'X-CSRF-Token':CSRF}};
  if(form){o.body=b;} else if(b){o.headers['Content-Type']='application/json';o.body=JSON.stringify(b);}
  const r=await fetch(u,o); return r.json().catch(()=>({}));
}
async function init(){
  const s=await (await fetch('/api/session')).json();
  if(!s.ok){location.href='/login';return;}
  CSRF=s.csrf; document.getElementById('who').textContent=s.email;
  const d=await (await fetch('/api/devices')).json();
  const el=document.getElementById('devices');
  if(!d.devices.length){el.innerHTML='<p>No devices yet. <a href="/claim">Pair one</a> — the code is on its screen.</p>';}
  else el.innerHTML=d.devices.map(dev=>`
    <div style='border:1px solid #ccc;padding:12px;margin:12px 0'>
      <b>${dev.name}</b> <small>${dev.device_id}</small><br>
      <small>last seen: ${dev.last_seen?new Date(dev.last_seen*1000).toLocaleString():'never'}
      · battery: ${dev.battery_pct??'—'}% · fw: ${dev.fw??'—'}</small><br>
      ${dev.override?'<b>📌 pinned photo active</b> <button onclick="clearOv(\\''+dev.device_id+'\\')">clear</button><br>':''}
      <img src='/api/devices/${dev.device_id}/preview' width='200'><br>
      <form onsubmit='return upload(event,"${dev.device_id}")'>
        <input type='file' name='photo' accept='image/*' required>
        <button>Push photo to device</button>
      </form><small>Push pins the photo immediately; the device shows it at its next wake.</small><br>
      <button onclick='renameDev("${dev.device_id}")'>Rename</button>
      <button onclick='unpair("${dev.device_id}")'>Unpair</button>
    </div>`).join('');
  const g=await (await fetch('/api/gphotos/status')).json();
  document.getElementById('srv').innerHTML =
    g.configured?(g.connected?`Google Photos: connected · ${g.cached} cached
    <button onclick="gpick()">Pick more photos</button>`:'<a href="/api/gphotos/connect"><button>Connect Google Photos</button></a>')
    :'<a href="/api/gphotos/connect">Set up Google Photos</a>';
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
async function logout(){await fetch('/api/auth/logout',{method:'POST'});location.href='/login';}
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
    port = APP.cfg.get("port", 8765)
    srv = http.server.ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"SpectraFrame server v2 on :{port} "
          f"(frame {W}x{H}, etag {APP.etag})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
