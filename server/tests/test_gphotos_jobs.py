"""Durable Google Photos import job tests."""
import json
import os
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import spectra_server


class FakePicker:
    def __init__(self):
        self.created = 0
        self.deleted = []

    def create_session(self):
        self.created += 1
        return {"id": "session-1", "pickerUri": "https://photos.example/pick"}

    def delete_session(self, session_id):
        self.deleted.append(session_id)


class GPhotosJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.config_path = os.path.join(self.tmp.name, "config.json")
        with open(self.config_path, "w") as f:
            json.dump({
                "google": {
                    "client_id": "123.apps.googleusercontent.com",
                    "client_secret": "secret",
                }
            }, f)
        self.server = spectra_server.Server(
            config_path=self.config_path,
            state_path=os.path.join(self.tmp.name, "state.json"),
            data_dir=os.path.join(self.tmp.name, "data"),
        )
        self.state_path = os.path.join(self.tmp.name, "state.json")
        self.data_dir = os.path.join(self.tmp.name, "data")
        self.picker = FakePicker()
        self.photos = SimpleNamespace(
            oauth=SimpleNamespace(connected=True),
            cache_dir=os.path.join(self.tmp.name, "photos"),
            blob_prefix="users/user-1/gphotos/",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_picker_job_is_persisted_and_duplicate_start_reuses_it(self):
        with patch.object(self.server, "photos_for", return_value=self.photos), \
                patch("gphotos_jobs.PickerClient",
                      return_value=self.picker):
            first = self.server.gphotos_pick("user-1")
            second = self.server.gphotos_pick("user-1")

        self.assertEqual(first, "https://photos.example/pick")
        self.assertEqual(second, first)
        self.assertEqual(self.picker.created, 1)
        self.assertEqual(
            self.server.store.get("gphotos_imports", "user-1")["status"],
            "waiting")

    def test_expired_job_resumes_and_persists_terminal_success(self):
        self.server.store.put("gphotos_imports", "user-1", {
            "session_id": "session-1",
            "picker_uri": "https://photos.example/pick",
            "status": "processing",
            "lease_owner": "dead-process",
            "lease_until": 0,
            "count": 0,
            "error": "",
        })
        self.server = spectra_server.Server(
            config_path=self.config_path,
            state_path=self.state_path,
            data_dir=self.data_dir,
        )

        def run(session_id, cleanup_session, on_ready):
            self.assertEqual(session_id, "session-1")
            self.assertFalse(cleanup_session)
            on_ready()
            self.assertEqual(
                self.server.store.get("gphotos_imports", "user-1")["status"],
                "processing")
            return 2

        flow = SimpleNamespace(run=run)
        with patch.object(self.server, "photos_for", return_value=self.photos), \
                patch("gphotos_jobs.PickerClient",
                      return_value=self.picker), \
                patch("gphotos_jobs.PickFlow", return_value=flow):
            self.assertTrue(self.server.gphotos_imports._process_next())

        job = self.server.store.get("gphotos_imports", "user-1")
        self.assertEqual(job["status"], "done")
        self.assertEqual(job["count"], 2)
        self.assertEqual(job["lease_until"], 0)
        self.assertEqual(self.picker.deleted, ["session-1"])

    def test_worker_startup_resumes_persisted_job(self):
        self.server.store.put("gphotos_imports", "user-1", {
            "session_id": "session-1",
            "picker_uri": "https://photos.example/pick",
            "status": "processing",
            "lease_owner": "previous-process",
            "lease_until": 0,
            "count": 0,
            "error": "",
        })
        self.server = spectra_server.Server(
            config_path=self.config_path,
            state_path=self.state_path,
            data_dir=self.data_dir,
        )
        with patch.object(self.server, "photos_for", return_value=self.photos), \
                patch("gphotos_jobs.PickerClient",
                      return_value=self.picker), \
                patch("gphotos_jobs.PickFlow",
                      return_value=SimpleNamespace(
                          run=lambda *args, **kwargs: 1)):
            self.server.gphotos_imports.start()
            deadline = time.time() + 2
            try:
                while time.time() < deadline:
                    job = self.server.store.get("gphotos_imports", "user-1")
                    if job["status"] == "done":
                        break
                    time.sleep(0.01)
            finally:
                self.server.gphotos_imports.stop()

        self.assertEqual(job["status"], "done")
        self.assertEqual(job["count"], 1)

    def test_failed_import_persists_error_and_keeps_session_for_retry(self):
        self.server.store.put("gphotos_imports", "user-1", {
            "session_id": "session-1",
            "picker_uri": "https://photos.example/pick",
            "status": "waiting",
            "lease_until": 0,
        })

        def fail(session_id, cleanup_session, on_ready):
            raise RuntimeError("temporary download failure")

        with patch.object(self.server, "photos_for", return_value=self.photos), \
                patch("gphotos_jobs.PickerClient",
                      return_value=self.picker), \
                patch("gphotos_jobs.PickFlow",
                      return_value=SimpleNamespace(run=fail)):
            self.assertTrue(self.server.gphotos_imports._process_next())

        job = self.server.store.get("gphotos_imports", "user-1")
        self.assertEqual(job["status"], "error")
        self.assertIn("temporary download failure", job["error"])
        self.assertEqual(job["lease_until"], 0)
        self.assertEqual(self.picker.deleted, [])


if __name__ == "__main__":
    unittest.main()
