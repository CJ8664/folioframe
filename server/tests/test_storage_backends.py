"""Tests for local persistent storage and Google OAuth integration."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from blobs import LocalBlobStore
from token_store import FileTokenStore, StoreTokenStore
from store import JsonStore


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


class TestTokenStores(unittest.TestCase):
    def test_file_round_trip(self):
        ts = FileTokenStore(os.path.join(tempfile.mkdtemp(), "t.json"))
        self.assertIsNone(ts.load())
        ts.save({"refresh_token": "r", "access_token": "a"})
        self.assertEqual(ts.load()["refresh_token"], "r")
        ts.clear()
        self.assertIsNone(ts.load())

    def test_store_round_trip(self):
        s = JsonStore(os.path.join(tempfile.mkdtemp(), "registry.json"))
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

    def test_photo_import_records_survive_store_restart(self):
        path = os.path.join(tempfile.mkdtemp(), "registry.json")
        store = JsonStore(path)
        store.put("photos_tokens", "user-1",
                  {"refresh_token": "refresh"})
        store.put("gphotos_imports", "user-1",
                  {"status": "processing", "session_id": "session-1"})

        restarted = JsonStore(path)
        self.assertEqual(
            restarted.get("photos_tokens", "user-1")["refresh_token"],
            "refresh")
        self.assertEqual(
            restarted.get("gphotos_imports", "user-1")["session_id"],
            "session-1")

    def test_import_claim_is_exclusive_and_reclaimable_after_expiry(self):
        store = JsonStore(os.path.join(tempfile.mkdtemp(), "registry.json"))
        store.put("gphotos_imports", "user-1",
                  {"status": "waiting", "lease_until": 0})

        self.assertIsNotNone(
            store.claim("gphotos_imports", "user-1", "worker-1", 60))
        self.assertTrue(store.renew_claim(
            "gphotos_imports", "user-1", "worker-1", 60))
        self.assertFalse(store.renew_claim(
            "gphotos_imports", "user-1", "worker-2", 60))
        self.assertIsNone(
            store.claim("gphotos_imports", "user-1", "worker-2", 60))
        self.assertFalse(store.finish_claim(
            "gphotos_imports", "user-1", "worker-2",
            {"status": "done"}))

        expired = store.get("gphotos_imports", "user-1")
        expired["lease_until"] = 0
        store.put("gphotos_imports", "user-1", expired)
        self.assertIsNotNone(
            store.claim("gphotos_imports", "user-1", "worker-2", 60))
        self.assertFalse(store.finish_claim(
            "gphotos_imports", "user-1", "worker-1",
            {"status": "done"}))
        self.assertTrue(store.finish_claim(
            "gphotos_imports", "user-1", "worker-2",
            {"status": "done", "count": 3}))


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
    def test_server_defaults_to_persistent_local_backends(self):
        tmp = tempfile.mkdtemp()
        cfg_path = os.path.join(tmp, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"source": "picsum"}, f)

        import spectra_server

        server = spectra_server.Server(
            config_path=cfg_path,
            state_path=os.path.join(tmp, "state.json"),
            data_dir=os.path.join(tmp, "data"),
        )
        self.assertIsInstance(server.store, JsonStore)
        self.assertIsInstance(server.blobs, LocalBlobStore)

        server.store.put("users", "user-1", {"name": "Frame owner"})
        server.blobs.put("photos/photo.jpg", b"photo")

        restarted = spectra_server.Server(
            config_path=cfg_path,
            state_path=os.path.join(tmp, "state.json"),
            data_dir=os.path.join(tmp, "data"),
        )
        self.assertEqual(
            restarted.store.get("users", "user-1")["name"], "Frame owner")
        self.assertEqual(restarted.blobs.get("photos/photo.jpg"), b"photo")

    def test_env_config_overrides_file(self):
        tmp = tempfile.mkdtemp()
        cfg_path = os.path.join(tmp, "config.json")
        with open(cfg_path, "w") as f:
            json.dump({"port": 1111, "source": "picsum"}, f)
        import spectra_server
        old = os.environ.get("SPECTRA_CONFIG_JSON")
        os.environ["SPECTRA_CONFIG_JSON"] = json.dumps(
            {"public_url": "https://frame.example.com"})
        try:
            server = spectra_server.Server(
                config_path=cfg_path,
                state_path=os.path.join(tmp, "state.json"),
                data_dir=os.path.join(tmp, "data"),
            )
            self.assertEqual(server.cfg["port"], 1111)
            self.assertEqual(server.public_url, "https://frame.example.com")
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
