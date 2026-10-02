#!/usr/bin/env python3
"""SpectraFrame companion server.

Implements PROTOCOL.md v1 for the firmware:
  GET /frame          packed 4bpp frame, ETag + 304 support
  GET /version        plain-text build number
  GET /firmware.bin   serves server/firmware/firmware.bin when present

Extras for humans:
  GET /               status page with preview + controls
  GET /preview.png    current frame as PNG
  POST /api/next      rotate immediately
  POST /api/source    {"name": ...} switch source
  GET /debug          JSON status

Config: server/config.json (created with defaults on first run).
State:  server/state.json (rotation history, persisted).
"""
import http.server
import json
import os
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

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(HERE, "config.json")
STATE_PATH = os.path.join(HERE, "state.json")
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
    def __init__(self):
        if not os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "w") as f:
                json.dump(DEFAULT_CONFIG, f, indent=2)
            print(f"wrote default {CONFIG_PATH}")
        with open(CONFIG_PATH) as f:
            self.cfg = json.load(f)
        self.state = {"history": {}, "last_rotation": 0}
        if os.path.exists(STATE_PATH):
            with open(STATE_PATH) as f:
                self.state.update(json.load(f))
        self.lock = threading.Lock()
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
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f)
        os.replace(tmp, STATE_PATH)

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


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, ctype, body, extra=None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        p = urllib.parse.urlparse(self.path).path
        if p == "/frame":
            if self.headers.get("If-None-Match") == APP.etag and APP.etag:
                self.send_response(304)
                self.end_headers()
                return
            if APP.frame is None:
                self.send_response(503)
                self.end_headers()
                return
            self._send(200, "application/octet-stream", APP.frame, {
                "ETag": APP.etag, "X-Frame-Format": "packed4bpp"})
        elif p == "/preview.png":
            if APP.preview is None:
                self.send_response(503)
                self.end_headers()
                return
            self._send(200, "image/png", APP.preview)
        elif p == "/version":
            self._send(200, "text/plain", APP.build.encode())
        elif p == "/firmware.bin":
            if os.path.exists(FW_PATH):
                with open(FW_PATH, "rb") as f:
                    self._send(200, "application/octet-stream", f.read())
            else:
                self.send_response(404)
                self.end_headers()
        elif p == "/debug":
            self._send(200, "application/json",
                        json.dumps(APP.describe()).encode())
        elif p == "/api/gphotos/connect":
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
        elif p == "/api/gphotos/callback":
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code, state = q.get("code", [""])[0], q.get("state", [""])[0]
            gp = APP.gphotos
            if not code or not gp.valid_state(state):
                self._send(400, "text/plain", b"bad oauth response")
            else:
                try:
                    gp.oauth.exchange_code(code)
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.end_headers()
                except Exception as e:
                    self._send(500, "text/plain",
                                f"connect failed: {e}".encode())
        elif p == "/api/gphotos/status":
            gp = APP.gphotos
            ps = gp.pick_state or {}
            self._send(200, "application/json", json.dumps({
                "configured": gp.configured,
                "connected": gp.oauth.connected,
                "cached": gp.cache_count(),
                "picking": ps.get("status") == "waiting",
                "picker_uri": ps.get("picker_uri", ""),
                "pick_status": ps.get("status", ""),
                "pick_count": ps.get("count", 0),
                "pick_error": ps.get("error", ""),
            }).encode())
        elif p == "/":
            d = APP.describe()
            opts = "".join(
                f"<option {'selected' if s == d['source']['name'] else ''}"
                f" value='{s}'>{s}</option>" for s in d["sources"])
            html = f"""<html><body><h2>SpectraFrame server</h2>
<img src='/preview.png' width='300'><p>source: {d['source']['name']}
etags: {d['etag']}<br>last rotation:
{time.strftime('%Y-%m-%d %H:%M', time.localtime(d['last_rotation']))}<br>
error: {d['last_error'] or 'none'}</p>
<form method='POST' action='/api/next'><button>Rotate now</button></form>
<form method='POST' action='/api/source'><select name='name'>{opts}</select>
<button>Switch source</button></form>
<h3>Google Photos</h3>
<div id='gphotos'>loading…</div>
<script>
fetch('/api/gphotos/status').then(r=>r.json()).then(s=>{{
  const el=document.getElementById('gphotos');
  if(!s.configured){{
    el.innerHTML='<a href="/api/gphotos/connect">Set up</a> (needs OAuth client — see docs/GOOGLE_PHOTOS.md)';
  }} else if(!s.connected){{
    el.innerHTML='<a href="/api/gphotos/connect"><button>Connect Google Photos</button></a>';
  }} else {{
    let h=`connected · ${{s.cached}} photos cached`;
    if(s.picking) h+=`<br>waiting for picks… <a href="${{s.picker_uri}}" target="_blank">open picker</a>`;
    else if(s.pick_status==='done') h+=`<br>last import: ${{s.pick_count}} photos`;
    else if(s.pick_status==='error') h+=`<br>import error: ${{s.pick_error}}`;
    else if(s.picker_uri) h+=`<br><a href="${{s.picker_uri}}" target="_blank">open picker</a>`;
    h+=`<br><form method='POST' action='/api/gphotos/pick' style='display:inline'>
<button>Pick more photos</button></form>
<form method='POST' action='/api/gphotos/disconnect' style='display:inline'>
<button>Disconnect</button></form>`;
    el.innerHTML=h;
  }}
}});
</script>
<p><a href='/debug'>debug JSON</a></p></body></html>"""
            self._send(200, "text/html", html.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        p = urllib.parse.urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length).decode()
        args = urllib.parse.parse_qs(body)
        if p == "/api/gphotos/pick":
            try:
                uri = APP.gphotos_pick()
                self._send(200, "application/json", json.dumps(
                    {"ok": True, "picker_uri": uri}).encode())
            except Exception as e:
                self._send(400, "application/json", json.dumps(
                    {"ok": False, "error": str(e)}).encode())
        elif p == "/api/gphotos/disconnect":
            APP.gphotos.oauth.disconnect()
            self._send(200, "application/json", b'{"ok": true}')
        elif p == "/api/next":
            ok = APP.rotate(force=True)
            self._send(200, "application/json",
                        json.dumps({"ok": ok}).encode())
        elif p == "/api/source":
            name = args.get("name", [""])[0]
            try:
                APP.switch_source(name)
                self._send(200, "application/json",
                            json.dumps({"ok": True}).encode())
            except ValueError as e:
                self._send(400, "application/json",
                            json.dumps({"ok": False, "error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()


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
    print(f"SpectraFrame server on :{port} "
          f"(frame {W}x{H}, etag {APP.etag})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
