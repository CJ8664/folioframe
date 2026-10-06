"""Security tests for Phase 1: Google sign-in, sessions, device pairing.

Covers the hard requirement: no access to any frame, photo, or device
control without pairing to an explicitly signed-in account.
"""
import http.client
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from io import BytesIO

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

import spectra_server
from auth import AuthManager, AuthError
from devices import (DeviceRegistry, AlreadyPaired, BadClaim, RateLimiter,
                     hash_token)
from store import JsonStore

CLIENT_ID = "test-client.apps.googleusercontent.com"
CLIENT_ID_2 = "second-client.apps.googleusercontent.com"


def fake_verifier_factory(claims):
    # claims: a single claims dict (token "good-token"), or
    # {token: claims} for multi-user tests.
    mapping = claims if "sub" not in claims else {"good-token": claims}

    def verify(token, client_id):
        if token not in mapping:
            raise ValueError("bad signature")
        return dict(mapping[token])
    return verify


GOOD_CLAIMS = {
    "aud": CLIENT_ID,
    "iss": "https://accounts.google.com",
    "exp": int(time.time()) + 3600,
    "sub": "google-sub-1",
    "email": "chirag@example.com",
    "email_verified": True,
    "name": "Chirag",
}


GOOD_CLAIMS_2 = {
    "aud": CLIENT_ID,
    "iss": "https://accounts.google.com",
    "exp": int(time.time()) + 3600,
    "sub": "google-sub-2",
    "email": "aashna@example.com",
    "email_verified": True,
    "name": "Aashna",
}


def make_auth(claims=None, allowlist=None, tmp=None, google_client_id=CLIENT_ID):
    store = JsonStore(os.path.join(tmp or tempfile.mkdtemp(),
                                   "registry.json"))
    # The service's own Google OAuth client (admin-configured, once).
    cfg = {"auth": {"allowlist": allowlist or []},
           "google": {"client_id": google_client_id,
                      "client_secret": "test-secret"}}
    return AuthManager(store, cfg,
                       verify_fn=fake_verifier_factory(claims or GOOD_CLAIMS))


class TestGoogleTokenVerification(unittest.TestCase):
    def test_forged_token_rejected(self):
        auth = make_auth()
        with self.assertRaises(AuthError):
            auth.verify_id_token("forged-token")

    def test_expired_token_rejected(self):
        claims = dict(GOOD_CLAIMS, exp=int(time.time()) - 3600)
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_wrong_audience_rejected(self):
        claims = dict(GOOD_CLAIMS, aud="evil.apps.googleusercontent.com")
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_wrong_issuer_rejected(self):
        claims = dict(GOOD_CLAIMS, iss="https://evil.example.com")
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_unverified_email_rejected(self):
        claims = dict(GOOD_CLAIMS, email_verified=False)
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_allowlist_enforced(self):
        auth = make_auth(allowlist=["someone-else@example.com"])
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_happy_path(self):
        auth = make_auth()
        sub, email, name = auth.verify_id_token("good-token")
        self.assertEqual(sub, "google-sub-1")
        self.assertEqual(email, "chirag@example.com")

    def test_server_client_id_required_and_validated(self):
        # Sign-in is impossible when the admin hasn't configured the
        # service's Google OAuth client (or configured it malformed).
        for bad in ("", "not-a-client", "evil.com",
                    "x.apps.googleusercontent.com.evil.com"):
            auth = make_auth(google_client_id=bad)
            with self.assertRaises(AuthError):
                auth.verify_id_token("good-token")

    def test_audience_must_equal_server_client(self):
        # The token's aud must match the service's OAuth client: a token
        # minted for any other client is rejected even if the signature is
        # otherwise fine.
        claims = dict(GOOD_CLAIMS, aud="other.apps.googleusercontent.com")
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")

    def test_missing_google_config_rejected(self):
        store = JsonStore(tempfile.mkdtemp() + "/r.json")
        auth = AuthManager(store, {"auth": {}},
                           verify_fn=fake_verifier_factory(GOOD_CLAIMS))
        with self.assertRaises(AuthError):
            auth.verify_id_token("good-token")


class TestSessions(unittest.TestCase):
    def test_cookie_round_trip(self):
        auth = make_auth()
        sid, csrf = auth.create_session("google-sub-1")
        cookie = f"sf_session={auth.cookie_value(sid)}"
        got_sid, sess = auth.session_from_cookie(cookie)
        self.assertEqual(got_sid, sid)
        self.assertEqual(sess["sub"], "google-sub-1")
        self.assertTrue(auth.check_csrf(sess, csrf))
        self.assertFalse(auth.check_csrf(sess, "wrong"))

    def test_tampered_cookie_rejected(self):
        auth = make_auth()
        sid, _ = auth.create_session("google-sub-1")
        bad = f"sf_session={sid}.{'0' * 64}"
        self.assertEqual(auth.session_from_cookie(bad), (None, None))

    def test_expired_session_rejected(self):
        auth = make_auth()
        sid, _ = auth.create_session("google-sub-1")
        sess = auth.store.get("sessions", sid)
        sess["created"] = int(time.time()) - 25 * 3600
        auth.store.put("sessions", sid, sess)
        cookie = f"sf_session={auth.cookie_value(sid)}"
        self.assertEqual(auth.session_from_cookie(cookie), (None, None))

    def test_logout_destroys_session(self):
        auth = make_auth()
        sid, _ = auth.create_session("google-sub-1")
        auth.destroy_session(sid)
        cookie = f"sf_session={auth.cookie_value(sid)}"
        self.assertEqual(auth.session_from_cookie(cookie), (None, None))


class TestDeviceRegistry(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.reg = DeviceRegistry(
            JsonStore(os.path.join(self.tmp, "registry.json")))

    def _pair(self, user="user-1", device="ff-aabbccddeeff"):
        code = self.reg.register(device, "gdeb0709e01", "2.0.0")["claim_code"]
        self.reg.claim(device, code, user)
        poll = self.reg.poll_claim(device, code)
        self.assertEqual(poll["status"], "claimed")
        return poll["device_token"]

    def test_claim_code_format(self):
        code = self.reg.register("ff-001122334455")["claim_code"]
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")

    def test_poll_before_approval_is_pending(self):
        code = self.reg.register("ff-001122334455")["claim_code"]
        self.assertEqual(
            self.reg.poll_claim("ff-001122334455", code)["status"], "pending")

    def test_token_delivered_exactly_once(self):
        device = "ff-aabbccddeeff"
        code = self.reg.register(device)["claim_code"]
        self.reg.claim(device, code, "user-1")
        token = self.reg.poll_claim(device, code)["device_token"]
        self.assertTrue(token)
        # Same code inside the grace window: re-delivers the SAME token
        # (covers a lost 200 response -- the device never got it).
        again = self.reg.poll_claim(device, code)
        self.assertEqual(again["device_token"], token)
        # Wrong code never delivers, even inside the grace window.
        with self.assertRaises(BadClaim):
            self.reg.poll_claim(device, "XXXX-XXXX")

    def test_bad_device_id_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.register("not-a-device")

    def test_token_hash_never_stores_plaintext(self):
        token = self._pair()
        dev = self.reg._get("ff-aabbccddeeff")
        self.assertEqual(dev["token_hash"], hash_token(token))
        # The plaintext is stashed only for the re-delivery grace window;
        # after it elapses the next poll wipes it.
        dev["claim_delivered_at"] = time.time() - 3600
        self.reg._put(dev)
        with self.assertRaises(BadClaim):
            self.reg.poll_claim("ff-aabbccddeeff", "XXXX-XXXX")
        dev = self.reg._get("ff-aabbccddeeff")
        self.assertNotIn(token, json.dumps(dev))

    def test_one_device_one_user(self):
        self._pair(user="user-1")
        code = self.reg.register("ff-aabbccddeeff")["claim_code"]
        with self.assertRaises(AlreadyPaired):
            self.reg.claim("ff-aabbccddeeff", code, "user-2")

    def test_unpair_revokes_token(self):
        token = self._pair()
        self.assertTrue(self.reg.unpair("ff-aabbccddeeff", "user-1"))
        self.assertIsNone(self.reg.verify_token(token))
        # stranger cannot unpair
        self._pair(user="user-1", device="ff-112233445566")
        self.assertFalse(self.reg.unpair("ff-112233445566", "user-2"))

    def test_expired_claim_code(self):
        code = self.reg.register("ff-001122334455")["claim_code"]
        dev = self.reg._get("ff-001122334455")
        dev["claim_expires"] = int(time.time()) - 1
        self.reg._put(dev)
        with self.assertRaises(BadClaim):
            self.reg.claim("ff-001122334455", code, "user-1")

    def test_rate_limiter(self):
        rl = RateLimiter(limit=3, window=60)
        self.assertTrue([rl.check("ip") for _ in range(3)])
        self.assertFalse(rl.check("ip"))
        self.assertTrue(rl.check("other-ip"))

    def test_heartbeat_sanitizes_device_controlled_values(self):
        self._pair()
        self.reg.heartbeat("ff-aabbccddeeff", {
            "battery_mv": "<script>alert(1)</script>",
            "battery_pct": 99999,
            "rssi": "not-a-number",
            "fw": "x" * 100,
        })
        dev = self.reg._get("ff-aabbccddeeff")
        # garbage numeric input is dropped, out-of-range clamped, fw cut
        self.assertNotIn("battery_mv", dev)
        self.assertEqual(dev["battery_pct"], 100)
        self.assertNotIn("rssi", dev)
        self.assertEqual(dev["fw"], "x" * 32)

    def test_register_truncates_device_strings(self):
        self.reg.register("ff-001122334455", panel="<b>evil</b>" + "y" * 50,
                          fw="1.0.0<script>")
        dev = self.reg._get("ff-001122334455")
        self.assertLessEqual(len(dev["panel"]), 32)
        self.assertLessEqual(len(dev["fw"]), 32)

    def test_self_unpair_invalidates_pending_claim(self):
        token = self._pair(user="user-1", device="ff-001122334455")
        # fresh claim code issued after pairing (e.g. user opened portal)
        code = self.reg.register("ff-001122334455")["claim_code"]
        # factory reset from the device itself
        self.assertTrue(
            self.reg.device_self_unpair("ff-001122334455"))
        self.assertIsNone(self.reg.verify_token(token))
        dev = self.reg._get("ff-001122334455")
        self.assertIsNone(dev.get("claim_code"))
        # the pending code no longer works
        with self.assertRaises(BadClaim):
            self.reg.poll_claim("ff-001122334455", code)


# --------------------------------------------------------------------------
# HTTP integration tests
# --------------------------------------------------------------------------

class TestHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        imgdir = os.path.join(cls.tmp, "imgs")
        os.makedirs(imgdir)
        Image.new("RGB", (64, 64), (255, 0, 0)).save(
            os.path.join(imgdir, "a.jpg"))
        cfg_path = os.path.join(cls.tmp, "config.json")
        with open(cfg_path, "w") as f:
            # The service's Google OAuth client (admin one-time setup).
            json.dump({"port": 0, "source": "folder",
                       "folder": {"dir": imgdir},
                       "auth": {"allowlist": []},
                       "google": {"client_id": CLIENT_ID,
                                  "client_secret": "test-secret"}}, f)
        spectra_server.APP = spectra_server.Server(
            config_path=cfg_path,
            state_path=os.path.join(cls.tmp, "state.json"),
            data_dir=os.path.join(cls.tmp, "data"))
        # inject fake Google verifier (two users for isolation tests)
        spectra_server.APP.auth._verify = fake_verifier_factory(
            {"good-token": GOOD_CLAIMS, "good-token-2": GOOD_CLAIMS_2})
        cls.srv = spectra_server.http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), spectra_server.Handler)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        hdrs = dict(resp.getheaders())
        conn.close()
        return resp.status, hdrs, data

    def login_as(self, token="good-token"):
        status, hdrs, data = self.req(
            "POST", "/api/auth/token",
            body=json.dumps({"id_token": token}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200, data[:200])
        j = json.loads(data)
        cookie = hdrs["Set-Cookie"].split(";")[0]
        return cookie, j["csrf"]

    def login(self):
        return self.login_as()

    def test_welcome_is_public_console_is_gated(self):
        # The welcome page is the only public page.
        status, _, data = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"Your memories,", data)
        self.assertIn(b"id='gbtn'", data)
        # /api/config exposes the (public) Google client ID for GIS.
        status, _, data = self.req("GET", "/api/config")
        j = json.loads(data)
        self.assertEqual(j["google_client_id"], CLIENT_ID)
        self.assertNotIn("test-secret", data.decode())
        # /login keeps old bookmarks working.
        status, hdrs, _ = self.req("GET", "/login")
        self.assertEqual(status, 302)
        self.assertEqual(hdrs["Location"], "/")
        # Everything else needs a session.
        status, _, _ = self.req("GET", "/api/devices")
        self.assertEqual(status, 401)
        status, _, _ = self.req("GET", "/claim")
        self.assertEqual(status, 302)
        # Signed in -> the console (account page).
        cookie, _ = self.login()
        status, _, data = self.req("GET", "/", headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn(b"Google Photos", data)

    def test_pwa_assets(self):
        # Web app manifest: valid, installable, references real icons.
        status, hdrs, data = self.req("GET", "/manifest.webmanifest")
        self.assertEqual(status, 200)
        self.assertIn("application/manifest+json",
                      hdrs.get("Content-Type", ""))
        m = json.loads(data)
        self.assertEqual(m["name"], "FolioFrame")
        self.assertEqual(m["display"], "standalone")
        self.assertEqual(m["start_url"], "/")
        sizes = {i["sizes"] for i in m["icons"]}
        self.assertIn("192x192", sizes)
        self.assertIn("512x512", sizes)
        # Service worker: served, not cached aggressively.
        status, hdrs, data = self.req("GET", "/sw.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript",
                      hdrs.get("Content-Type", ""))
        self.assertIn(b"no-cache", hdrs.get("Cache-Control", "").encode())
        self.assertIn(b"fetch", data)
        # Icons: real PNG bytes.
        for icon in ("icon-192.png", "icon-512.png", "icon-180.png",
                     "icon-maskable-512.png"):
            status, hdrs, data = self.req("GET", "/static/" + icon)
            self.assertEqual(status, 200, icon)
            self.assertIn("image/png", hdrs.get("Content-Type", ""))
            self.assertTrue(data.startswith(b"\x89PNG"), icon)
        # Path traversal is blocked.
        status, _, _ = self.req("GET", "/static/../spectra_server.py")
        self.assertEqual(status, 404)

    def test_pages_declare_pwa(self):
        status, _, data = self.req("GET", "/")
        self.assertEqual(status, 200, "/")
        body = data.decode()
        self.assertIn("rel='manifest'", body, "/")
        self.assertIn("theme-color", body, "/")
        self.assertIn("apple-touch-icon", body, "/")
        self.assertIn("serviceWorker", body, "/")
        # Signed-in pages: console and claim.
        cookie, _ = self.login()
        for path in ("/", "/claim"):
            status, _, data = self.req("GET", path,
                                       headers={"Cookie": cookie})
            self.assertEqual(status, 200, path)
            body = data.decode()
            self.assertIn("rel='manifest'", body, path)
            self.assertIn("serviceWorker", body, path)

    def test_nosniff_header_set(self):
        # Every response carries X-Content-Type-Options: nosniff so
        # text/plain error bodies can't be sniffed as HTML (XSS).
        for path in ("/", "/api/config", "/manifest.webmanifest",
                     "/sw.js", "/static/icon-192.png"):
            status, hdrs, _ = self.req("GET", path)
            self.assertEqual(status, 200, path)
            self.assertEqual(hdrs.get("X-Content-Type-Options"), "nosniff",
                             path)

    def test_oversized_json_body_rejected(self):
        # A huge Content-Length on a JSON endpoint is rejected (400),
        # not read into memory.
        status, _, _ = self.req(
            "POST", "/api/auth/token",
            body=" ",
            headers={"Content-Type": "application/json",
                     "Content-Length": str(2 * 1024 * 1024)})
        self.assertEqual(status, 400)

    def test_oversized_upload_rejected(self):
        cookie, csrf = self.login()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf,
             "Content-Type": "multipart/form-data; boundary=B",
             "Content-Length": str(26 * 1024 * 1024)}
        status, _, data = self.req(
            "POST", "/api/devices/ff-aaaa1111bbbb/photos/upload",
            body=" ", headers=h)
        self.assertEqual(status, 400)
        self.assertIn(b"too large", data)

    def test_login_validates_token(self):
        for body in ({}, {"id_token": "forged"}):
            status, _, _ = self.req(
                "POST", "/api/auth/token", body=json.dumps(body),
                headers={"Content-Type": "application/json"})
            self.assertEqual(status, 401, body)
        # A stray client_id field is simply ignored.
        status, _, _ = self.req(
            "POST", "/api/auth/token",
            body=json.dumps({"id_token": "good-token",
                             "client_id": "ignored"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)

    def test_forged_login_rejected(self):
        status, _, data = self.req(
            "POST", "/api/auth/token",
            body=json.dumps({"id_token": "forged"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 401)

    def test_csrf_enforced(self):
        cookie, _ = self.login()
        status, _, _ = self.req(
            "POST", "/api/devices/claim",
            body=json.dumps({"code": "XXXX-XXXX"}),
            headers={"Content-Type": "application/json",
                     "Cookie": cookie})  # no CSRF header
        self.assertEqual(status, 403)

    def test_full_pairing_and_frame_flow(self):
        cookie, csrf = self.login()
        h = {"Content-Type": "application/json", "Cookie": cookie,
             "X-CSRF-Token": csrf}
        # 1. device registers -> claim code
        status, _, data = self.req(
            "POST", "/v1/device/register",
            body=json.dumps({"device_id": "ff-aaaa1111bbbb",
                             "panel": "gdeb0709e01", "fw": "2.0.0"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 201)
        code = json.loads(data)["claim_code"]
        # 2. device polls -> pending
        status, _, data = self.req(
            "POST", "/v1/device/claim",
            body=json.dumps({"device_id": "ff-aaaa1111bbbb",
                             "claim_code": code}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(json.loads(data)["status"], "pending")
        # 3. human claims via console
        status, _, data = self.req(
            "POST", "/api/devices/claim",
            body=json.dumps({"code": code}), headers=h)
        self.assertEqual(status, 200)
        # 4. device polls -> gets token exactly once
        status, _, data = self.req(
            "POST", "/v1/device/claim",
            body=json.dumps({"device_id": "ff-aaaa1111bbbb",
                             "claim_code": code}),
            headers={"Content-Type": "application/json"})
        j = json.loads(data)
        self.assertEqual(j["status"], "claimed")
        token = j["device_token"]
        # 5. frame without auth -> 401
        status, _, _ = self.req("GET", "/v1/device/frame")
        self.assertEqual(status, 401)
        # 6. frame with token -> 200
        status, hdrs, data = self.req(
            "GET", "/v1/device/frame",
            headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertEqual(hdrs["X-Frame-Format"], "packed4bpp")
        etag = hdrs["ETag"]
        # 7. conditional fetch -> 304
        status, _, _ = self.req(
            "GET", "/v1/device/frame",
            headers={"Authorization": f"Bearer {token}",
                     "If-None-Match": etag})
        self.assertEqual(status, 304)
        # 8. device appears in my devices
        status, _, data = self.req("GET", "/api/devices", headers=h)
        devs = json.loads(data)["devices"]
        self.assertEqual(len(devs), 1)
        self.assertEqual(devs[0]["device_id"], "ff-aaaa1111bbbb")

    def _raw_request(self, raw: bytes) -> bytes:
        s = socket.create_connection(("127.0.0.1", self.port), timeout=10)
        s.sendall(raw)
        resp = b""
        try:
            while True:
                chunk = s.recv(4096)
                if not chunk:
                    break
                resp += chunk
        except socket.timeout:
            pass
        s.close()
        return resp

    def test_csrf_form_garbage_content_length(self):
        # A garbage Content-Length on the CSRF form fallback must not
        # crash the handler: expect a clean 403, not a dead connection.
        cookie, _ = self.login()
        raw = (f"POST /api/source HTTP/1.1\r\nHost: x\r\n"
               f"Cookie: {cookie}\r\n"
               "Content-Type: application/x-www-form-urlencoded\r\n"
               "Content-Length: garbage\r\n"
               "Connection: close\r\n\r\n").encode()
        resp = self._raw_request(raw)
        self.assertIn(b"403", resp.split(b"\r\n")[0])

    def test_csrf_form_oversized_body_ignored(self):
        # A huge form body on the CSRF fallback is ignored (not read into
        # memory): still a clean 403 for the missing token.
        cookie, _ = self.login()
        body = b"csrf=" + b"x" * 200000
        raw = (f"POST /api/source HTTP/1.1\r\nHost: x\r\n"
               f"Cookie: {cookie}\r\n"
               "Content-Type: application/x-www-form-urlencoded\r\n"
               f"Content-Length: {len(body)}\r\n"
               "Connection: close\r\n\r\n").encode() + body
        resp = self._raw_request(raw)
        self.assertIn(b"403", resp.split(b"\r\n")[0])

    def test_flash_page_is_public_without_binaries(self):
        # No login: /flash explains that nothing is published yet.
        # Point FW_DIR at an empty dir so the test is hermetic even when
        # real binaries are packaged in the repo.
        tmp = tempfile.mkdtemp()
        old = spectra_server.FW_DIR
        spectra_server.FW_DIR = tmp
        try:
            status, _, data = self.req("GET", "/flash")
            self.assertEqual(status, 200)
            self.assertIn(b"No firmware published", data)
            self.assertNotIn(b"<esp-web-install-button", data)
            # manifest + binaries 404 cleanly
            for path in ("/flash/manifest.json", "/flash/firmware.bin",
                         "/flash/bootloader.bin", "/flash/evil.bin"):
                status, _, _ = self.req("GET", path)
                self.assertEqual(status, 404, path)
        finally:
            spectra_server.FW_DIR = old

    def test_flash_manifest_and_binaries_when_published(self):
        tmp = tempfile.mkdtemp()
        for name, _ in spectra_server.FLASH_PARTS:
            with open(os.path.join(tmp, name), "wb") as f:
                f.write(b"fake-" + name.encode())
        # Versioned binaries for the /flash version picker.
        for v in ("2.0.0", "3.0.0"):
            with open(os.path.join(tmp, f"firmware-{v}.bin"), "wb") as f:
                f.write(b"fake-firmware-" + v.encode())
        old = spectra_server.FW_DIR
        spectra_server.FW_DIR = tmp
        try:
            status, _, data = self.req("GET", "/flash")
            self.assertEqual(status, 200)
            # Inline flash console (no popup): 30/70 split, version picker,
            # connect button, and the embedded ewt-install-dialog.
            self.assertIn(b"flash-split", data)
            self.assertIn(b"id='fwver'", data)
            self.assertIn(b"id='flash-go'", data)
            self.assertIn(b"id='console-wrap'", data)
            self.assertIn(b"ewt-install-dialog", data)
            self.assertNotIn(b"<esp-web-install-button", data)
            status, hdrs, data = self.req("GET", "/flash/manifest.json")
            self.assertEqual(status, 200)
            m = json.loads(data)
            self.assertEqual(m["name"], "FolioFrame")
            self.assertEqual(m["builds"][0]["chipFamily"], "ESP32-S3")
            parts = m["builds"][0]["parts"]
            self.assertEqual(
                [(p["path"], p["offset"]) for p in parts],
                [(f"/flash/{n}", o)
                 for n, o in spectra_server.FLASH_PARTS])
            status, _, data = self.req("GET", "/flash/firmware.bin")
            self.assertEqual(status, 200)
            self.assertEqual(data, b"fake-firmware.bin")
            # versioned manifest: ?version= selects the older build
            status, _, data = self.req(
                "GET", "/flash/manifest.json?version=2.0.0")
            self.assertEqual(status, 200)
            m = json.loads(data)
            self.assertEqual(m["version"], "2.0.0")
            fw_paths = [p["path"] for p in m["builds"][0]["parts"]]
            self.assertIn("/flash/firmware-2.0.0.bin", fw_paths)
            self.assertNotIn("/flash/firmware.bin", fw_paths)
            # unknown version -> 404
            status, _, _ = self.req(
                "GET", "/flash/manifest.json?version=9.9.9")
            self.assertEqual(status, 404)
            # versioned binary download
            status, _, data = self.req("GET", "/flash/firmware-2.0.0.bin")
            self.assertEqual(status, 200)
            self.assertEqual(data, b"fake-firmware-2.0.0")
            # traversal attempts don't escape the firmware dir
            for path in ("/flash/../spectra_server.py", "/flash/.bin",
                         "/flash/firmware-..%2f..%2f.bin"):
                status, _, _ = self.req("GET", path)
                self.assertIn(status, (400, 404), path)
        finally:
            spectra_server.FW_DIR = old

    def test_esp_web_tools_static_subpath(self):
        status, hdrs, data = self.req(
            "GET", "/static/esp-web-tools/install-button.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", hdrs.get("Content-Type", ""))
        self.assertTrue(data.startswith(b"const "))
        # no escaping the vendored dir
        status, _, _ = self.req("GET", "/static/esp-web-tools/../icon-192.png")
        self.assertEqual(status, 404)

    def test_ota_version_is_firmware_manifest(self):        # The firmware's OtaManifest parser needs "build=N" lines; a bare
        # number would be rejected and OTA would silently never happen.
        cookie, csrf = self.login()
        h = {"Content-Type": "application/json", "Cookie": cookie,
             "X-CSRF-Token": csrf}
        status, _, data = self.req(
            "POST", "/v1/device/register",
            body=json.dumps({"device_id": "ff-0a0000000001",
                             "panel": "gdeb0709e01", "fw": "2.0.0"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 201)
        code = json.loads(data)["claim_code"]
        self.req("POST", "/api/devices/claim",
                 body=json.dumps({"code": code}), headers=h)
        status, _, data = self.req(
            "POST", "/v1/device/claim",
            body=json.dumps({"device_id": "ff-0a0000000001",
                             "claim_code": code}),
            headers={"Content-Type": "application/json"})
        token = json.loads(data)["device_token"]
        # unauthenticated -> 401
        status, _, _ = self.req("GET", "/v1/device/ota/version")
        self.assertEqual(status, 401)
        # authenticated -> manifest with a numeric build line
        status, _, data = self.req(
            "GET", "/v1/device/ota/version",
            headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        body = data.decode()
        self.assertTrue(body.startswith("build="), body)
        self.assertTrue(body.split("=", 1)[1].split("\n")[0].strip().isdigit())
        # md5 line is optional (only when a firmware binary is published),
        # but when present it must be 32 hex chars or the firmware rejects it.
        for line in body.splitlines():
            if line.startswith("md5="):
                md5 = line.split("=", 1)[1].strip()
                self.assertRegex(md5, r"^[0-9a-f]{32}$")

    def test_second_user_cannot_claim_paired_device(self):
        cookie, csrf = self.login()
        h = {"Content-Type": "application/json", "Cookie": cookie,
             "X-CSRF-Token": csrf}
        self.req("POST", "/v1/device/register",
                 body=json.dumps({"device_id": "ff-cccc3333dddd"}),
                 headers={"Content-Type": "application/json"})
        # second registration issues a fresh code; claim it as user 1
        status, _, data = self.req(
            "POST", "/v1/device/register",
            body=json.dumps({"device_id": "ff-cccc3333dddd"}),
            headers={"Content-Type": "application/json"})
        code = json.loads(data)["claim_code"]
        status, _, _ = self.req("POST", "/api/devices/claim",
                                body=json.dumps({"code": code}), headers=h)
        self.assertEqual(status, 200)
        # simulate a *different* user by re-registering (new code) and
        # claiming directly through the registry as user-2
        reg = spectra_server.APP.devices
        code2 = reg.register("ff-cccc3333dddd")["claim_code"]
        with self.assertRaises(AlreadyPaired):
            reg.claim("ff-cccc3333dddd", code2, "google-sub-2")

    def test_cross_user_device_isolation(self):
        cookie, csrf = self.login()  # user-1
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        reg = spectra_server.APP.devices
        code = reg.register("ff-eeee5555ffff")["claim_code"]
        reg.claim("ff-eeee5555ffff", code, "google-sub-2")  # other user
        # user-1 must not see it: 404, not 403 (no existence leak)
        status, _, _ = self.req("GET",
                                "/api/devices/ff-eeee5555ffff/preview",
                                headers=h)
        self.assertEqual(status, 404)
        status, _, _ = self.req("DELETE", "/api/devices/ff-eeee5555ffff",
                                headers=h)
        self.assertEqual(status, 404)

    def test_upload_override_and_clear(self):
        cookie, csrf = self.login()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        reg = spectra_server.APP.devices
        code = reg.register("ff-ffff6666aaaa")["claim_code"]
        reg.claim("ff-ffff6666aaaa", code, "google-sub-1")
        poll = reg.poll_claim("ff-ffff6666aaaa", code)
        token = poll["device_token"]

        # build multipart upload
        img = Image.new("RGB", (64, 64), (0, 255, 0))
        buf = __import__("io").BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        boundary = "BOUNDARY123"
        body = (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="photo"; filename="leaf.png"\r\n'
                f"Content-Type: image/png\r\n\r\n").encode() + png + \
               f"\r\n--{boundary}--\r\n".encode()
        status, _, data = self.req(
            "POST", "/api/devices/ff-ffff6666aaaa/photos/upload", body=body,
            headers={"Content-Type":
                     f"multipart/form-data; boundary={boundary}", **h})
        self.assertEqual(status, 200, data[:200])
        j = json.loads(data)
        self.assertTrue(j["ok"])

        # device frame is now the override
        status, hdrs, _ = self.req(
            "GET", "/v1/device/frame",
            headers={"Authorization": f"Bearer {token}"})
        self.assertEqual(status, 200)
        self.assertEqual(hdrs["ETag"], j["etag"])

        # preview reflects override
        status, _, data = self.req(
            "GET", "/api/devices/ff-ffff6666aaaa/preview", headers=h)
        self.assertEqual(status, 200)

        # clear -> back to normal
        status, _, _ = self.req(
            "DELETE", "/api/devices/ff-ffff6666aaaa/photos/override",
            headers=h)
        self.assertEqual(status, 200)

    def test_gphotos_connect_uses_server_client(self):
        # No per-user secret step exists anymore: connect uses the
        # service's OAuth client straight away.
        cookie, csrf = self.login()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        # An https origin is passed through (302): Google itself refuses to
        # redirect to a URI never registered for the client, so Google's
        # registered-redirect-URI check is the enforcement point.
        status, hdrs, _ = self.req(
            "GET", "/api/gphotos/connect?origin=https://frame.example.com",
            headers={"Cookie": cookie})
        self.assertEqual(status, 302)
        loc = hdrs.get("Location", "")
        self.assertIn("https://accounts.google.com/", loc)
        self.assertIn("client_id=" + CLIENT_ID, loc)
        self.assertIn("include_granted_scopes=true", loc)
        # status shows no secrets, no client IDs -- just state
        status, _, data = self.req("GET", "/api/gphotos/status",
                                   headers={"Cookie": cookie})
        j = json.loads(data)
        self.assertNotIn("client_id", j)
        self.assertNotIn("secret", json.dumps(j).lower())
        self.assertFalse(j["connected"])
        # per-user isolation: a second user's Photos state is separate
        cookie2, _ = self.login_as("good-token-2")
        status, _, data = self.req(
            "GET", "/api/gphotos/status", headers={"Cookie": cookie2})
        j2 = json.loads(data)
        self.assertFalse(j2["connected"])
        # the removed per-user secret endpoint is gone
        status, _, _ = self.req(
            "POST", "/api/gphotos/setup",
            body=json.dumps({"client_secret": "s"}),
            headers={"Content-Type": "application/json", **h})
        self.assertEqual(status, 404)

    def test_connect_origin_validated(self):
        cookie, csrf = self.login()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        # An https origin is passed through (302): Google itself refuses to
        # redirect to a URI the user never registered for their client, so
        # Google's registered-redirect-URI check is the enforcement point.
        status, hdrs, _ = self.req(
            "GET", "/api/gphotos/connect?origin=https://evil.example.com",
            headers={"Cookie": cookie})
        self.assertEqual(status, 302)
        self.assertIn("https://accounts.google.com/",
                      hdrs.get("Location", ""))
        # ...but malformed / insecure origins are rejected outright.
        for bad in ("javascript:alert(1)", "http://192.168.1.5:8765",
                    "notaurl", ""):
            status, _, _ = self.req(
                "GET", "/api/gphotos/connect?origin=" + bad,
                headers={"Cookie": cookie})
            self.assertEqual(status, 400, bad)
        # localhost http is allowed (local dev).
        status, _, _ = self.req(
            "GET", "/api/gphotos/connect?origin=http://localhost:8765",
            headers={"Cookie": cookie})
        self.assertEqual(status, 302)

    def test_account_client_rotation_removed(self):
        # The per-user client rotation endpoint is gone with
        # bring-your-own OAuth.
        cookie, csrf = self.login()
        h = {"Content-Type": "application/json", "Cookie": cookie,
             "X-CSRF-Token": csrf}
        status, _, _ = self.req(
            "PATCH", "/api/account/client",
            body=json.dumps({"client_id": CLIENT_ID_2}), headers=h)
        self.assertEqual(status, 404)

    def test_legacy_anonymous_frame_is_gone(self):
        status, _, _ = self.req("GET", "/frame")
        self.assertEqual(status, 404)


class TestPhotoPicker(unittest.TestCase):
    """Photo picker page + /api/photos endpoints (thumbnails, editor save)."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cfg_path = os.path.join(cls.tmp, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"port": 0, "source": "picsum",
                       "auth": {"allowlist": []},
                       "google": {"client_id": CLIENT_ID,
                                  "client_secret": "test-secret"}}, f)
        spectra_server.APP = spectra_server.Server(
            config_path=cfg_path,
            state_path=os.path.join(cls.tmp, "state.json"),
            data_dir=os.path.join(cls.tmp, "data"))
        spectra_server.APP.auth._verify = fake_verifier_factory(
            {"good-token": GOOD_CLAIMS, "good-token-2": GOOD_CLAIMS_2})
        cls.srv = spectra_server.http.server.ThreadingHTTPServer(
            ("127.0.0.1", 0), spectra_server.Handler)
        cls.port = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.thread.join(timeout=5)

    def req(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port,
                                          timeout=10)
        conn.request(method, path, body=body, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        hdrs = dict(resp.getheaders())
        conn.close()
        return resp.status, hdrs, data

    def login_as(self, token="good-token"):
        status, hdrs, data = self.req(
            "POST", "/api/auth/token",
            body=json.dumps({"id_token": token}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200, data[:200])
        j = json.loads(data)
        cookie = hdrs["Set-Cookie"].split(";")[0]
        return cookie, j["csrf"]

    def seed_photo(self, sub="google-sub-1", name="picker-test.jpg",
                   color=(200, 30, 30)):
        buf = BytesIO()
        Image.new("RGB", (800, 600), color).save(buf, "JPEG", quality=90)
        spectra_server.APP.photos_for(sub).source.save(name, buf.getvalue())
        return name

    def test_photos_page_gated(self):
        status, hdrs, _ = self.req("GET", "/photos")
        self.assertEqual(status, 302)
        self.assertEqual(hdrs["Location"], "/")
        cookie, _ = self.login_as()
        status, _, data = self.req("GET", "/photos",
                                   headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        body = data.decode()
        self.assertIn("<title>Photos - FolioFrame</title>", body)
        self.assertIn("/static/folioframe.css", body)
        self.assertIn("/static/photos.js", body)
        self.assertIn("id='photoGrid'", body)
        self.assertIn("id='einkCanvas'", body)
        self.assertIn("id='editorCanvas'", body)

    def test_console_links_photos(self):
        cookie, _ = self.login_as()
        status, _, data = self.req("GET", "/",
                                   headers={"Cookie": cookie})
        self.assertEqual(status, 200)
        self.assertIn("href='/photos'", data.decode())

    def test_photo_api_auth(self):
        status, _, _ = self.req("GET", "/api/photos")
        self.assertEqual(status, 401)
        status, _, _ = self.req("GET", "/api/photos/x/thumb")
        self.assertEqual(status, 401)

    def test_photo_list_and_thumbs(self):
        pid = self.seed_photo()
        spaced = self.seed_photo(name="my photo.jpg")
        cookie, _ = self.login_as()
        h = {"Cookie": cookie}
        status, _, data = self.req("GET", "/api/photos", headers=h)
        self.assertEqual(status, 200)
        j = json.loads(data)
        self.assertTrue(j["ok"])
        self.assertIn(pid, [p["id"] for p in j["photos"]])
        self.assertIn(spaced, [p["id"] for p in j["photos"]])
        status, hdrs, data = self.req(
            "GET", "/api/photos/" + pid + "/thumb", headers=h)
        self.assertEqual(status, 200)
        self.assertIn("image/jpeg", hdrs.get("Content-Type", ""))
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        thumb_len = len(data)
        # Filenames with spaces arrive URL-encoded and still resolve.
        status, _, data = self.req(
            "GET", "/api/photos/my%20photo.jpg/thumb", headers=h)
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        status, _, data = self.req(
            "GET", "/api/photos/" + pid + "/full", headers=h)
        self.assertEqual(status, 200)
        self.assertTrue(data.startswith(b"\xff\xd8\xff"))
        self.assertGreater(len(data), thumb_len)
        # Unknown id and traversal attempts are 404, not 500.
        status, _, _ = self.req("GET", "/api/photos/nope.jpg/thumb",
                                headers=h)
        self.assertEqual(status, 404)
        status, _, _ = self.req("GET", "/api/photos/../x/thumb", headers=h)
        self.assertEqual(status, 404)

    def test_photo_libraries_are_per_user(self):
        self.seed_photo(sub="google-sub-1", name="mine.jpg")
        cookie2, _ = self.login_as("good-token-2")
        status, _, data = self.req("GET", "/api/photos",
                                   headers={"Cookie": cookie2})
        j = json.loads(data)
        self.assertEqual(j["photos"], [])
        status, _, _ = self.req("GET", "/api/photos/mine.jpg/full",
                                headers={"Cookie": cookie2})
        self.assertEqual(status, 404)

    def test_edit_replaces_cached_photo(self):
        pid = self.seed_photo(color=(200, 30, 30))
        cookie, csrf = self.login_as()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf,
             "Content-Type": "image/jpeg"}
        # No CSRF -> 403.
        status, _, _ = self.req(
            "POST", "/api/photos/" + pid + "/edit", body=b"xx",
            headers={"Cookie": cookie,
                     "Content-Type": "image/jpeg"})
        self.assertEqual(status, 403)
        # Non-image -> 400.
        status, _, data = self.req(
            "POST", "/api/photos/" + pid + "/edit", body=b"not an image",
            headers=h)
        self.assertEqual(status, 400)
        # Unknown id -> 404.
        buf = BytesIO()
        Image.new("RGB", (1200, 1600), (30, 30, 200)).save(buf, "JPEG")
        status, _, _ = self.req("POST", "/api/photos/nope.jpg/edit",
                                body=buf.getvalue(), headers=h)
        self.assertEqual(status, 404)
        # Real edit: blue canvas replaces the red photo.
        status, _, data = self.req("POST", "/api/photos/" + pid + "/edit",
                                   body=buf.getvalue(), headers=h)
        self.assertEqual(status, 200, data[:200])
        self.assertTrue(json.loads(data)["ok"])
        img = spectra_server.APP.photos_for("google-sub-1").source.load(pid)
        r, g, b = img.getpixel((600, 800))
        self.assertGreater(b, 150)
        self.assertLess(r, 100)

    def test_photos_js_served(self):
        status, hdrs, data = self.req("GET", "/static/photos.js")
        self.assertEqual(status, 200)
        self.assertIn("application/javascript",
                      hdrs.get("Content-Type", ""))
        self.assertIn(b"ditherImage", data)
        self.assertIn(b"serpentine", data.lower())


if __name__ == "__main__":
    unittest.main()
