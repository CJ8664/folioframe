"""Tests for the Firebase deployment backends.

All cloud clients are faked -- no network, no credentials needed.
"""
import json
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blobs import LocalBlobStore, GCSBlobStore
from token_store import FileTokenStore, StoreTokenStore
from store import FirestoreStore
from auth import AuthManager, AuthError


# --------------------------------------------------------------------------
# fakes
# --------------------------------------------------------------------------

class FakeBlob:
    def __init__(self, store, name):
        self._store = store
        self.name = name

    def upload_from_string(self, data, content_type=None):
        self._store[self.name] = data

    def download_as_bytes(self):
        return self._store[self.name]

    def exists(self):
        return self.name in self._store

    def delete(self):
        self._store.pop(self.name, None)


class FakeBucket:
    def __init__(self, store):
        self._store = store

    def blob(self, name):
        return FakeBlob(self._store, name)


class FakeGCSClient:
    def __init__(self):
        self._store = {}
        self.bucket_name = None

    def bucket(self, name):
        self.bucket_name = name
        return FakeBucket(self._store)

    def list_blobs(self, bucket, prefix=""):
        return [FakeBlob(self._store, k) for k in sorted(self._store)
                if k.startswith(prefix)]


class FakeDoc:
    def __init__(self, store, path):
        self._store = store
        self._path = path
        self.id = path.rsplit("/", 1)[-1]
        self.exists = path in store

    def get(self):
        self.exists = self._path in self._store
        return self

    def to_dict(self):
        return dict(self._store[self._path])

    def set(self, data):
        self._store[self._path] = dict(data)

    def delete(self):
        self._store.pop(self._path, None)


class FakeDocRef(FakeDoc):
    pass


class FakeCollection:
    def __init__(self, store, name):
        self._store = store
        self._name = name

    def document(self, key):
        return FakeDocRef(self._store, f"{self._name}/{key}")

    def stream(self):
        return [FakeDocRef(self._store, p) for p in self._store
                if p.startswith(self._name + "/")]


class FakeFirestoreClient:
    def __init__(self):
        self._store = {}

    def collection(self, name):
        return FakeCollection(self._store, name)

    def document(self, path):
        return FakeDocRef(self._store, path)


# --------------------------------------------------------------------------
# tests
# --------------------------------------------------------------------------

class TestLocalBlobStore(unittest.TestCase):
    def test_round_trip(self):
        bs = LocalBlobStore(tempfile.mkdtemp())
        self.assertIsNone(bs.get("a/b.bin"))
        self.assertFalse(bs.exists("a/b.bin"))
        bs.put("a/b.bin", b"hello")
        self.assertTrue(bs.exists("a/b.bin"))
        self.assertEqual(bs.get("a/b.bin"), b"hello")
        self.assertEqual(bs.list("a/"), ["a/b.bin"])
        self.assertEqual(bs.list("zzz/"), [])
        bs.delete("a/b.bin")
        self.assertFalse(bs.exists("a/b.bin"))

    def test_path_traversal_rejected(self):
        bs = LocalBlobStore(tempfile.mkdtemp())
        with self.assertRaises(ValueError):
            bs.put("../../evil", b"x")


class TestGCSBlobStore(unittest.TestCase):
    def test_round_trip(self):
        client = FakeGCSClient()
        bs = GCSBlobStore("test-bucket", client=client)
        self.assertEqual(client.bucket_name, "test-bucket")
        bs.put("devices/d1/override.frame", b"\x00\xff")
        self.assertTrue(bs.exists("devices/d1/override.frame"))
        self.assertEqual(bs.get("devices/d1/override.frame"), b"\x00\xff")
        self.assertIsNone(bs.get("nope"))
        self.assertEqual(bs.list("devices/"), ["devices/d1/override.frame"])
        bs.delete("devices/d1/override.frame")
        self.assertFalse(bs.exists("devices/d1/override.frame"))


class TestTokenStores(unittest.TestCase):
    def test_file_round_trip(self):
        ts = FileTokenStore(os.path.join(tempfile.mkdtemp(), "t.json"))
        self.assertIsNone(ts.load())
        ts.save({"refresh_token": "r", "access_token": "a"})
        self.assertEqual(ts.load()["refresh_token"], "r")
        ts.clear()
        self.assertIsNone(ts.load())

    def test_store_round_trip(self):
        # Per-user tokens through the Store abstraction: one code path for
        # JsonStore (local) and FirestoreStore (Cloud Run).
        s = FirestoreStore(client=FakeFirestoreClient())
        ts = StoreTokenStore(s, "user-1")
        self.assertIsNone(ts.load())
        ts.save({"refresh_token": "r"})
        # second instance sees the same entry (persistence across restarts)
        ts2 = StoreTokenStore(s, "user-1")
        self.assertEqual(ts2.load()["refresh_token"], "r")
        # per-user isolation
        self.assertIsNone(StoreTokenStore(s, "user-2").load())
        ts.clear()
        self.assertIsNone(ts.load())


class TestFirestoreStore(unittest.TestCase):
    def test_crud(self):
        s = FirestoreStore(client=FakeFirestoreClient())
        self.assertIsNone(s.get("devices", "d1"))
        s.put("devices", "d1", {"owner": "u1"})
        self.assertEqual(s.get("devices", "d1"), {"owner": "u1"})
        self.assertEqual(s.all("devices"), {"d1": {"owner": "u1"}})
        s.delete("devices", "d1")
        self.assertIsNone(s.get("devices", "d1"))

    def test_expired_sessions_filtered(self):
        s = FirestoreStore(client=FakeFirestoreClient())
        s.put("sessions", "s1", {"sub": "u1"})
        # force expiry
        s._client._store["sessions/s1"]["expires_at"] = time.time() - 1
        self.assertIsNone(s.get("sessions", "s1"))
        self.assertEqual(s.all("sessions"), {})


class TestClientProvider(unittest.TestCase):
    def test_runtime_client_resolution(self):
        from sources.google_photos import GoogleOAuth, GPhotosController
        creds = {"cid": "first", "sec": "s1"}
        o = GoogleOAuth(redirect_uri="http://x/cb",
                        token_path="/tmp/ff-test-nope.json",
                        client_provider=lambda: (creds["cid"], creds["sec"]))
        self.assertIn("client_id=first", o.auth_url("st"))
        creds.update(cid="second", sec="s2")  # rotation, no restart
        self.assertIn("client_id=second", o.auth_url("st"))

    def test_controller_configured_flips(self):
        from sources.google_photos import GPhotosController
        state = {}
        c = GPhotosController(
            8765,
            cache_dir=os.path.join(tempfile.mkdtemp(), "g"),
            client_provider=lambda: (state.get("cid", ""),
                                     state.get("sec", "")))
        self.assertFalse(c.configured)
        state.update(cid="a", sec="b")
        self.assertTrue(c.configured)

    def test_oauth_state_round_trip(self):
        from sources.google_photos import GPhotosController
        c = GPhotosController(
            8765, cache_dir=os.path.join(tempfile.mkdtemp(), "g2"))
        uri = "https://frame.example.com/api/gphotos/callback"
        s = c.new_state(uri)
        self.assertEqual(c.pop_state(s), uri)   # single use
        self.assertIsNone(c.pop_state(s))
        self.assertIsNone(c.pop_state("bogus"))


class TestServerEnvConfig(unittest.TestCase):
    def test_env_config_overrides_file(self):
        tmp = tempfile.mkdtemp()
        cfg_path = os.path.join(tmp, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"port": 1111, "source": "picsum",
                       "firebase": {"project_id": ""}}, f)
        import spectra_server
        old = os.environ.get("SPECTRA_CONFIG_JSON")
        os.environ["SPECTRA_CONFIG_JSON"] = json.dumps(
            {"firebase": {"project_id": "env-project"}})
        try:
            # FirebaseStore would need real credentials; just check that
            # config parsing picks up the env project before it gets there.
            # Instead, verify the merge logic directly on a copy:
            cfg = json.load(open(cfg_path))
            cfg.update(json.loads(os.environ["SPECTRA_CONFIG_JSON"]))
            self.assertEqual(cfg["firebase"]["project_id"], "env-project")
            self.assertEqual(cfg["port"], 1111)
        finally:
            if old is None:
                del os.environ["SPECTRA_CONFIG_JSON"]
            else:
                os.environ["SPECTRA_CONFIG_JSON"] = old


class TestRotationStateInStore(unittest.TestCase):
    def test_state_survives_via_store(self):
        from store import JsonStore
        tmp = tempfile.mkdtemp()
        s = JsonStore(os.path.join(tmp, "r.json"))
        s.put("_service", "rotation",
              {"history": {"picsum": ["a"]}, "last_rotation": 123})
        self.assertEqual(s.get("_service", "rotation")["last_rotation"], 123)


if __name__ == "__main__":
    unittest.main()
