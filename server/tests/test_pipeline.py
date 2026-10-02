import io
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PIL import Image

import pipeline
from pipeline import VALID_NIBBLES


def solid(color, w=64, h=48):
    return Image.new("RGB", (w, h), color)


class TestPipeline(unittest.TestCase):
    def test_pack_layout(self):
        nibbles = bytearray([0x0, 0xF, 0x2, 0xD])
        packed = pipeline.pack(nibbles, 4, 1)
        self.assertEqual(packed, bytes([0x0F, 0x2D]))  # high nibble first

    def test_pack_size(self):
        n = bytearray([0x0]) * (1200 * 1600)
        self.assertEqual(len(pipeline.pack(n, 1200, 1600)), 960000)

    def test_floyd_nibbles_valid(self):
        img = solid((200, 100, 50))
        out = pipeline.dither_floyd_steinberg(img)
        self.assertEqual(len(out), 64 * 48)
        self.assertTrue(all(n in VALID_NIBBLES for n in out))

    def test_floyd_solid_colors(self):
        self.assertEqual(
            set(pipeline.dither_floyd_steinberg(solid((255, 255, 255)))), {0x0})
        self.assertEqual(
            set(pipeline.dither_floyd_steinberg(solid((0, 0, 0)))), {0xF})

    def test_ordered_valid(self):
        out = pipeline.dither_ordered(solid((128, 128, 128)))
        self.assertTrue(all(n in VALID_NIBBLES for n in out))

    def test_cover_dims(self):
        img = Image.new("RGB", (800, 600), (10, 20, 30))
        self.assertEqual(pipeline.cover(img, 1200, 1600).size, (1200, 1600))
        tall = Image.new("RGB", (600, 800), (10, 20, 30))
        self.assertEqual(pipeline.cover(tall, 1200, 1600).size, (1200, 1600))

    def test_process_image_full_frame(self):
        img = Image.new("RGB", (800, 600), (90, 140, 200))
        frame = pipeline.process_image(img, 1200, 1600)
        self.assertEqual(len(frame), 960000)

    def test_etag(self):
        e1 = pipeline.frame_etag(b"abc")
        e2 = pipeline.frame_etag(b"abc")
        self.assertEqual(e1, e2)
        self.assertTrue(e1.startswith('"') and e1.endswith('"'))
        self.assertNotEqual(e1, pipeline.frame_etag(b"abd"))

    def test_preview_png(self):
        frame = pipeline.process_image(solid((90, 140, 200)), 120, 160)
        png = pipeline.preview_png(frame, 120, 160)
        img = Image.open(io.BytesIO(png))
        self.assertEqual(img.format, "PNG")
        self.assertEqual(img.mode, "RGB")

    def test_load_image_exif(self):
        # EXIF orientation 6 (rotate 90 CW) must be normalized.
        img = Image.new("RGB", (100, 60), (1, 2, 3))
        exif = img.getexif()
        exif[274] = 6
        buf = io.BytesIO()
        img.save(buf, "JPEG", exif=exif)
        loaded = pipeline.load_image(buf.getvalue())
        self.assertEqual(loaded.size, (60, 100))


if __name__ == "__main__":
    unittest.main()
