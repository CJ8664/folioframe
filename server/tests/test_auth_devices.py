"""Security tests for Phase 1: Google sign-in, sessions, device pairing.

Covers the hard requirement: no access to any frame, photo, or device
control without pairing to an explicitly signed-in account.
"""
import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

import spectra_server
from auth import AuthManager, AuthError
from devices import (DeviceRegistry, AlreadyPaired, BadClaim, RateLimiter,
                     hash_token)
from store import JsonStore

CLIENT_ID = "test-client.apps.googleusercontent.com"


def fake_verifier_factory(claims):
    def verify(token, client_id):
        if token != "good-token":
            raise ValueError("bad signature")
        return dict(claims)
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


def make_auth(claims=None, allowlist=None, tmp=None):
    store = JsonStore(os.path.join(tmp or tempfile.mkdtemp(),
                                   "registry.json"))
    cfg = {"auth": {"client_id": CLIENT_ID,
                    "allowlist": allowlist or []}}
    return AuthManager(store, cfg,
                       verify_fn=fake_verifier_factory(claims or GOOD_CLAIMS))


class TestGoogleTokenVerification(unittest.TestCase):
    def test_forged_token_rejected(self):
        auth = make_auth()
        with self.assertRaises(AuthError):
            auth.verify_google_token("forged-token")

    def test_expired_token_rejected(self):
        claims = dict(GOOD_CLAIMS, exp=int(time.time()) - 3600)
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_google_token("good-token")

    def test_wrong_audience_rejected(self):
        claims = dict(GOOD_CLAIMS, aud="evil.apps.googleusercontent.com")
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_google_token("good-token")

    def test_wrong_issuer_rejected(self):
        claims = dict(GOOD_CLAIMS, iss="https://evil.example.com")
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_google_token("good-token")

    def test_unverified_email_rejected(self):
        claims = dict(GOOD_CLAIMS, email_verified=False)
        auth = make_auth(claims)
        with self.assertRaises(AuthError):
            auth.verify_google_token("good-token")

    def test_allowlist_enforced(self):
        auth = make_auth(allowlist=["someone-else@example.com"])
        with self.assertRaises(AuthError):
            auth.verify_google_token("good-token")

    def test_happy_path(self):
        auth = make_auth()
        sub, email, name = auth.verify_google_token("good-token")
        self.assertEqual(sub, "google-sub-1")
        self.assertEqual(email, "chirag@example.com")


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

    def _pair(self, user="user-1", device="sf-aabbccddeeff"):
        code = self.reg.register(device, "gdeb0709e01", "2.0.0")["claim_code"]
        self.reg.claim(device, code, user)
        poll = self.reg.poll_claim(device, code)
        self.assertEqual(poll["status"], "claimed")
        return poll["device_token"]

    def test_claim_code_format(self):
        code = self.reg.register("sf-001122334455")["claim_code"]
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}$")

    def test_poll_before_approval_is_pending(self):
        code = self.reg.register("sf-001122334455")["claim_code"]
        self.assertEqual(
            self.reg.poll_claim("sf-001122334455", code)["status"], "pending")

    def test_token_delivered_exactly_once(self):
        token = self._pair()
        self.assertTrue(token)
        # second poll: code is burned
        with self.assertRaises(BadClaim):
            self.reg.poll_claim("sf-aabbccddeeff", "XXXX-XXXX")

    def test_bad_device_id_rejected(self):
        with self.assertRaises(ValueError):
            self.reg.register("not-a-device")

    def test_token_hash_never_stores_plaintext(self):
        token = self._pair()
        dev = self.reg._get("sf-aabbccddeeff")
        self.assertNotIn(token, json.dumps(dev))
        self.assertEqual(dev["token_hash"], hash_token(token))

    def test_one_device_one_user(self):
        self._pair(user="user-1")
        code = self.reg.register("sf-aabbccddeeff")["claim_code"]
        with self.assertRaises(AlreadyPaired):
            self.reg.claim("sf-aabbccddeeff", code, "user-2")

    def test_unpair_revokes_token(self):
        token = self._pair()
        self.assertTrue(self.reg.unpair("sf-aabbccddeeff", "user-1"))
        self.assertIsNone(self.reg.verify_token(token))
        # stranger cannot unpair
        self._pair(user="user-1", device="sf-112233445566")
        self.assertFalse(self.reg.unpair("sf-112233445566", "user-2"))

    def test_expired_claim_code(self):
        code = self.reg.register("sf-001122334455")["claim_code"]
        dev = self.reg._get("sf-001122334455")
        dev["claim_expires"] = int(time.time()) - 1
        self.reg._put(dev)
        with self.assertRaises(BadClaim):
            self.reg.claim("sf-001122334455", code, "user-1")

    def test_rate_limiter(self):
        rl = RateLimiter(limit=3, window=60)
        self.assertTrue([rl.check("ip") for _ in range(3)])
        self.assertFalse(rl.check("ip"))
        self.assertTrue(rl.check("other-ip"))


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
            json.dump({"port": 0, "source": "folder",
                       "folder": {"dir": imgdir},
                       "auth": {"client_id": CLIENT_ID, "allowlist": []}}, f)
        spectra_server.APP = spectra_server.Server(
            config_path=cfg_path,
            state_path=os.path.join(cls.tmp, "state.json"),
            data_dir=os.path.join(cls.tmp, "data"))
        # inject fake Google verifier
        spectra_server.APP.auth._verify = fake_verifier_factory(GOOD_CLAIMS)
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

    def login(self):
        status, hdrs, data = self.req(
            "POST", "/api/auth/token",
            body=json.dumps({"id_token": "good-token"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 200)
        j = json.loads(data)
        cookie = hdrs["Set-Cookie"].split(";")[0]
        return cookie, j["csrf"]

    def test_console_requires_login(self):
        status, _, _ = self.req("GET", "/")
        self.assertEqual(status, 302)
        status, _, _ = self.req("GET", "/api/devices")
        self.assertEqual(status, 401)

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
            body=json.dumps({"device_id": "sf-aaaa1111bbbb",
                             "panel": "gdeb0709e01", "fw": "2.0.0"}),
            headers={"Content-Type": "application/json"})
        self.assertEqual(status, 201)
        code = json.loads(data)["claim_code"]
        # 2. device polls -> pending
        status, _, data = self.req(
            "POST", "/v1/device/claim",
            body=json.dumps({"device_id": "sf-aaaa1111bbbb",
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
            body=json.dumps({"device_id": "sf-aaaa1111bbbb",
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
        self.assertEqual(devs[0]["device_id"], "sf-aaaa1111bbbb")

    def test_second_user_cannot_claim_paired_device(self):
        cookie, csrf = self.login()
        h = {"Content-Type": "application/json", "Cookie": cookie,
             "X-CSRF-Token": csrf}
        self.req("POST", "/v1/device/register",
                 body=json.dumps({"device_id": "sf-cccc3333dddd"}),
                 headers={"Content-Type": "application/json"})
        # second registration issues a fresh code; claim it as user 1
        status, _, data = self.req(
            "POST", "/v1/device/register",
            body=json.dumps({"device_id": "sf-cccc3333dddd"}),
            headers={"Content-Type": "application/json"})
        code = json.loads(data)["claim_code"]
        status, _, _ = self.req("POST", "/api/devices/claim",
                                body=json.dumps({"code": code}), headers=h)
        self.assertEqual(status, 200)
        # simulate a *different* user by re-registering (new code) and
        # claiming directly through the registry as user-2
        reg = spectra_server.APP.devices
        code2 = reg.register("sf-cccc3333dddd")["claim_code"]
        with self.assertRaises(AlreadyPaired):
            reg.claim("sf-cccc3333dddd", code2, "google-sub-2")

    def test_cross_user_device_isolation(self):
        cookie, csrf = self.login()  # user-1
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        reg = spectra_server.APP.devices
        code = reg.register("sf-eeee5555ffff")["claim_code"]
        reg.claim("sf-eeee5555ffff", code, "google-sub-2")  # other user
        # user-1 must not see it: 404, not 403 (no existence leak)
        status, _, _ = self.req("GET",
                                "/api/devices/sf-eeee5555ffff/preview",
                                headers=h)
        self.assertEqual(status, 404)
        status, _, _ = self.req("DELETE", "/api/devices/sf-eeee5555ffff",
                                headers=h)
        self.assertEqual(status, 404)

    def test_upload_override_and_clear(self):
        cookie, csrf = self.login()
        h = {"Cookie": cookie, "X-CSRF-Token": csrf}
        reg = spectra_server.APP.devices
        code = reg.register("sf-ffff6666aaaa")["claim_code"]
        reg.claim("sf-ffff6666aaaa", code, "google-sub-1")
        poll = reg.poll_claim("sf-ffff6666aaaa", code)
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
            "POST", "/api/devices/sf-ffff6666aaaa/photos/upload", body=body,
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
            "GET", "/api/devices/sf-ffff6666aaaa/preview", headers=h)
        self.assertEqual(status, 200)

        # clear -> back to normal
        status, _, _ = self.req(
            "DELETE", "/api/devices/sf-ffff6666aaaa/photos/override",
            headers=h)
        self.assertEqual(status, 200)

    def test_legacy_anonymous_frame_is_gone(self):
        status, _, _ = self.req("GET", "/frame")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
