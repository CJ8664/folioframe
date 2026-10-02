#!/usr/bin/env python3
"""Reference frame server implementing PROTOCOL.md v1 (stdlib only).

Serves:
  GET /frame          packed 4bpp test pattern (1200x1600), ETag + 304 support
  GET /version        plain-text build number
  GET /firmware.bin   placeholder (replace with a real build for OTA tests)

Usage: python3 tools/frame_server.py [port]
Point the device's Image URL at http://<host>:<port>/frame
"""
import hashlib
import http.server
import sys

W, H = 1200, 1600
# Spectra 6 nibble codes: white, green, red, yellow, blue, black
BARS = [0x0, 0x2, 0x6, 0xB, 0xD, 0xF]


def make_frame() -> bytes:
    buf = bytearray(W * H // 2)
    bar_w = W // len(BARS)
    for y in range(H):
        for x in range(0, W, 2):
            bar = min(x // bar_w, len(BARS) - 1)
            nib = BARS[bar] if (y // 40) % 2 == 0 else 0xF - BARS[bar]
            buf[(y * W + x) // 2] = (BARS[bar] << 4) | (nib & 0xF)
    return bytes(buf)


FRAME = make_frame()
ETAG = '"' + hashlib.md5(FRAME).hexdigest() + '"'
BUILD = "1"


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        print(" ".join(str(x) for x in a[1:]))

    def do_GET(self):
        if self.path == "/frame":
            if self.headers.get("If-None-Match") == ETAG:
                self.send_response(304)
                self.end_headers()
                return
            print("headers from device:",
                  {k: v for k, v in self.headers.items()
                   if k.lower().startswith("x-")})
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(FRAME)))
            self.send_header("ETag", ETAG)
            self.send_header("X-Frame-Format", "packed4bpp")
            self.end_headers()
            self.wfile.write(FRAME)
        elif self.path == "/version":
            body = BUILD.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/firmware.bin":
            self.send_response(404)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    srv = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"frame server on :{port}  (ETag {ETAG})")
    srv.serve_forever()
