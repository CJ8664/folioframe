import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

from sources.google_photos import (GoogleOAuth, PickerClient, PickFlow,
                                   _parse_duration, PICKER_BASE)
from sources.google_photos import GooglePhotosSource


class FakeHttp:
    """Canned (method, path-suffix) -> (status, body) responses."""

    def __init__(self):
        self.calls = []
        self.routes = {}

    def __call__(self, method, url, headers=None, data=None):
        self.calls.append((method, url, headers, data))
        path = url.split("?")[0]
        for (m, suffix), (status, body) in self.routes.items():
            if m == method and path.endswith(suffix):
                if isinstance(body, dict):
                    body = json.dumps(body).encode()
                return status, body
        raise AssertionError(f"unexpected call: {method} {url}")

    def auth_headers(self):
        return [c[2].get("Authorization") for c in self.calls
                if c[2] and "Authorization" in c[2]]


def make_oauth(tmp, http):
    return GoogleOAuth("cid", "csecret",
                       "http://localhost:8765/api/gphotos/callback",
                       os.path.join(tmp, "tokens.json"), http)


class TestParseDuration(unittest.TestCase):
    def test_values(self):
        self.assertEqual(_parse_duration("2s"), 2.0)
        self.assertEqual(_parse_duration("1.5s"), 1.5)
        self.assertEqual(_parse_duration("600s"), 600.0)
        self.assertEqual(_parse_duration(""), 0.0)
        self.assertEqual(_parse_duration(None), 0.0)
        self.assertEqual(_parse_duration("bogus"), 0.0)


class TestOAuth(unittest.TestCase):
    def test_auth_url(self):
        http = FakeHttp()
        with tempfile.TemporaryDirectory() as tmp:
            url = make_oauth(tmp, http).auth_url("state123")
        self.assertIn("client_id=cid", url)
        self.assertIn("scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2F"
                      "photospicker.mediaitems.readonly", url)
        self.assertIn("access_type=offline", url)
        self.assertIn("prompt=consent", url)
        self.assertIn("state=state123", url)
        self.assertIn("redirect_uri=", url)

    def test_exchange_and_store(self):
        http = FakeHttp()
        http.routes[("POST", "/token")] = (200, {
            "access_token": "at", "refresh_token": "rt", "expires_in": 3600})
        with tempfile.TemporaryDirectory() as tmp:
            o = make_oauth(tmp, http)
            self.assertFalse(o.connected)
            o.exchange_code("code123")
            self.assertTrue(o.connected)
            # token file is owner-only
            mode = oct(os.stat(os.path.join(tmp, "tokens.json")).st_mode)
            self.assertTrue(mode.endswith("600"))
            # code actually sent
            _, _, _, data = http.calls[0]
            self.assertIn(b"code=code123", data)
            self.assertIn(b"grant_type=authorization_code", data)

    def test_refresh_preserves_refresh_token(self):
        http = FakeHttp()
        http.routes[("POST", "/token")] = (200, {
            "access_token": "new-at", "expires_in": 3600})  # no refresh_token
        with tempfile.TemporaryDirectory() as tmp:
            o = make_oauth(tmp, http)
            # seed an expired token
            with open(os.path.join(tmp, "tokens.json"), "w") as f:
                json.dump({"access_token": "old", "refresh_token": "rt",
                           "expires_at": 1}, f)
            self.assertEqual(o.access_token(), "new-at")
            _, _, _, data = http.calls[0]
            self.assertIn(b"grant_type=refresh_token", data)
            self.assertIn(b"refresh_token=rt", data)
            # still connected afterwards
            self.assertTrue(o.connected)


class TestPickerClient(unittest.TestCase):
    def _client(self, tmp, routes):
        http = FakeHttp()
        http.routes.update(routes)
        o = make_oauth(tmp, http)
        with open(os.path.join(tmp, "tokens.json"), "w") as f:
            json.dump({"access_token": "at", "refresh_token": "rt",
                       "expires_at": 9999999999}, f)
        return PickerClient(o, http), http

    def test_create_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, http = self._client(tmp, {
                ("POST", "/v1/sessions"): (200, {
                    "id": "sess1",
                    "pickerUri": "https://photos.google.com/picker/abc",
                    "pollingConfig": {"pollInterval": "2s",
                                      "timeoutIn": "600s"},
                    "mediaItemsSet": False}),
            })
            s = c.create_session()
            self.assertEqual(s["id"], "sess1")
            self.assertIn("picker", s["pickerUri"])
            self.assertEqual(
                http.auth_headers(), ["Bearer at"])

    def test_picker_api_host(self):
        # Regression: the Picker API lives on photospicker.googleapis.com,
        # not the restricted Library API host. Using the wrong host made
        # every "Pick photos" attempt fail server-side (2026-10-04).
        self.assertEqual(PICKER_BASE, "https://photospicker.googleapis.com/v1")

    def test_list_pagination(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, _ = self._client(tmp, {
                ("GET", "/v1/mediaItems"): (200, {
                    "mediaItems": [{"id": "m1"}],
                    "nextPageToken": "tok"}),
            })
            # second page: override by query inspection
            orig = c._http

            def two_pages(method, url, headers=None, data=None):
                if "pageToken=tok" in url:
                    return 200, json.dumps({"mediaItems": [{"id": "m2"}]}
                                           ).encode()
                return orig(method, url, headers, data)

            c._http = two_pages
            p1 = c.list_media_items("sess1")
            p2 = c.list_media_items("sess1", p1["nextPageToken"])
            self.assertEqual(p1["mediaItems"][0]["id"], "m1")
            self.assertEqual(p2["mediaItems"][0]["id"], "m2")
            self.assertNotIn("nextPageToken", p2)

    def test_download_uses_bearer_and_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            c, http = self._client(tmp, {})
            http.routes[("GET", "/photo=d")] = (200, b"JPEGDATA")
            data = c.download("https://lh3.google.com/photo")
            self.assertEqual(data, b"JPEGDATA")
            method, url, headers, _ = http.calls[-1]
            self.assertTrue(url.endswith("=d"))
            self.assertEqual(headers["Authorization"], "Bearer at")


class TestPickFlow(unittest.TestCase):
    def _flow(self, tmp, session_seq, items_pages):
        calls = {"n": 0, "deletes": 0}

        def fake(method, url, headers=None, data=None):
            path = url.split("?")[0]
            if method == "DELETE" and "/v1/sessions/" in path:
                calls["deletes"] += 1
                return 200, b"{}"
            if method == "GET" and path.endswith("/v1/mediaItems"):
                page = items_pages[1] if "pageToken=" in url else items_pages[0]
                return 200, json.dumps(page).encode()
            if method == "GET" and "/v1/sessions/" in path:
                i = min(calls["n"], len(session_seq) - 1)
                calls["n"] += 1
                return 200, json.dumps(session_seq[i]).encode()
            if method == "GET":  # download
                return 200, b"IMAGEDATA"
            raise AssertionError(url)

        o = make_oauth(tmp, fake)
        with open(os.path.join(tmp, "tokens.json"), "w") as f:
            json.dump({"access_token": "at", "refresh_token": "rt",
                       "expires_at": 9999999999}, f)
        cache = os.path.join(tmp, "cache")
        return PickFlow(PickerClient(o, fake), cache), calls

    def test_import_skips_video_and_cleans_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow, calls = self._flow(
                tmp,
                [{"mediaItemsSet": False,
                  "pollingConfig": {"pollInterval": "0s", "timeoutIn": "5s"}},
                 {"mediaItemsSet": True}],
                [{"mediaItems": [
                    {"id": "p1", "type": "TYPE_IMAGE",
                     "mediaFile": {"baseUrl": "https://x/p1",
                                   "mimeType": "image/jpeg",
                                   "filename": "p1.jpg"}},
                    {"id": "v1", "type": "TYPE_VIDEO",
                     "mediaFile": {"baseUrl": "https://x/v1",
                                   "mimeType": "video/mp4",
                                   "filename": "v1.mp4"}},
                ]}, {}])
            n = flow.run("sess1", poll=lambda s: None)
            self.assertEqual(n, 1)
            files = os.listdir(os.path.join(tmp, "cache"))
            self.assertEqual(files, ["p1.jpg"])
            self.assertEqual(calls["deletes"], 1)  # session cleaned up

    def test_timeout(self):
        with tempfile.TemporaryDirectory() as tmp:
            flow, _ = self._flow(
                tmp,
                [{"mediaItemsSet": False,
                  "pollingConfig": {"pollInterval": "0s",
                                    "timeoutIn": "0.05s"}}],
                [{}, {}])
            with self.assertRaises(TimeoutError):
                flow.run("sess1", poll=lambda s: None)


class TestSource(unittest.TestCase):
    def test_unseen_first_from_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("b.jpg", "a.jpg"):
                Image.new("RGB", (8, 8), (1, 2, 3)).save(
                    os.path.join(tmp, name))
            src = GooglePhotosSource({"cache_dir": tmp})
            first = src.next_id([])
            self.assertIn(first, ("a.jpg", "b.jpg"))
            second = src.next_id([first])
            self.assertNotEqual(second, first)
            img = src.load(second)
            self.assertEqual(img.size, (8, 8))

    def test_empty_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = GooglePhotosSource({"cache_dir": tmp})
            self.assertIsNone(src.next_id([]))
            self.assertEqual(src.describe()["cached"], 0)


if __name__ == "__main__":
    unittest.main()
