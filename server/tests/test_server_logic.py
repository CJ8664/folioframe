import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

import spectra_server
from sources import pick_unseen
from sources.dashboard import DashboardSource
from sources.folder import FolderSource
from sources.picsum import PicsumSource
from sources.url import UrlSource


class TestQuiet(unittest.TestCase):
    def test_disabled(self):
        self.assertFalse(spectra_server.in_quiet(720, "09:00", "09:00"))

    def test_simple(self):
        self.assertTrue(spectra_server.in_quiet(720, "09:00", "17:00"))
        self.assertFalse(spectra_server.in_quiet(539, "09:00", "17:00"))
        self.assertFalse(spectra_server.in_quiet(1020, "09:00", "17:00"))

    def test_wrap(self):
        self.assertTrue(spectra_server.in_quiet(1410, "22:00", "07:00"))
        self.assertTrue(spectra_server.in_quiet(0, "22:00", "07:00"))
        self.assertTrue(spectra_server.in_quiet(419, "22:00", "07:00"))
        self.assertFalse(spectra_server.in_quiet(420, "22:00", "07:00"))
        self.assertFalse(spectra_server.in_quiet(720, "22:00", "07:00"))


class TestPickUnseen(unittest.TestCase):
    def test_unseen_first(self):
        ids = ["a", "b", "c"]
        seen = set()
        for _ in range(3):
            pick = pick_unseen(ids, [], __import__("random").Random(1))
            seen.add(pick)
            ids = [i for i in ids if i != pick]
        self.assertEqual(seen, {"a", "b", "c"})

    def test_reshuffle_when_exhausted(self):
        self.assertIn(
            pick_unseen(["a"], ["a"], __import__("random").Random(1)), ["a"])

    def test_empty(self):
        self.assertIsNone(
            pick_unseen([], [], __import__("random").Random(1)))


class TestFolderSource(unittest.TestCase):
    def test_scan_and_load(self):
        with tempfile.TemporaryDirectory() as d:
            for name, color in (("b.png", (0, 0, 255)),
                                ("a.jpg", (255, 0, 0))):
                Image.new("RGB", (32, 32), color).save(
                    os.path.join(d, name))
            open(os.path.join(d, "note.txt"), "w").write("x")
            src = FolderSource({"dir": d})
            ids = src._ids()
            self.assertEqual(ids, ["a.jpg", "b.png"])  # sorted, images only
            img = src.load("a.jpg")
            self.assertEqual(img.size, (32, 32))
            nxt = src.next_id([])
            self.assertIn(nxt, ids)

    def test_missing_dir(self):
        src = FolderSource({"dir": "/nonexistent-xyz"})
        self.assertEqual(src._ids(), [])
        self.assertIsNone(src.next_id([]))


class TestDashboardSource(unittest.TestCase):
    def test_always_now(self):
        src = DashboardSource({})
        self.assertEqual(src.next_id(["now", "now"]), "now")

    def test_renders(self):
        src = DashboardSource({"lat": 36.17, "lon": -115.14})
        img = src.load("now")
        self.assertEqual(img.size, (1200, 1600))
        self.assertEqual(img.mode, "RGB")


class TestSeedSources(unittest.TestCase):
    def test_picsum_avoids_recent(self):
        src = PicsumSource({})
        hist = [src.next_id([]) for _ in range(5)]
        nxt = src.next_id(hist)
        self.assertNotIn(nxt, hist)

    def test_url_describe(self):
        src = UrlSource({"template": "https://x/{seed}"})
        self.assertEqual(src.describe()["template"], "https://x/{seed}")


if __name__ == "__main__":
    unittest.main()
