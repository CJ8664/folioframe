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


class TestToneAndDrc(unittest.TestCase):
    def test_tone_keeps_geometry(self):
        img = solid((100, 120, 140), 32, 24)
        out = pipeline.apply_tone(img, {"saturation": 1.5, "contrast": 1.2,
                                        "exposure": 0.5})
        self.assertEqual(out.size, (32, 24))
        self.assertEqual(out.mode, "RGB")

    def test_tone_exposure_brightens(self):
        img = solid((100, 100, 100), 8, 8)
        out = pipeline.apply_tone(img, {"exposure": 1.0})
        self.assertGreater(out.getpixel((0, 0))[0], 150)

    def test_drc_off_is_identity(self):
        img = solid((90, 140, 200), 16, 16)
        out = pipeline.apply_drc(img, {"drc": "off"})
        self.assertEqual(list(out.getdata()), list(img.getdata()))

    def test_drc_compresses_into_palette_range(self):
        # black->white gradient: after display DRC the lightness must sit
        # inside the palette's measured luminance range.
        grad = Image.new("RGB", (64, 16))
        grad.putdata([(v, v, v) for v in range(256) for _ in range(4)])
        out = pipeline.apply_drc(grad, {"drc": "display", "drc_strength": 1.0,
                                        "preserve_white": False})
        Ls = [pipeline._palette_lab_lightness(px)
              for px in out.getdata()][::16]
        blackL = min(pipeline._PALETTE_LS)
        whiteL = max(pipeline._PALETTE_LS)
        for L in Ls:
            self.assertGreaterEqual(L, blackL - 3)
            self.assertLessEqual(L, whiteL + 3)

    def test_drc_preserve_white(self):
        img = solid((250, 250, 248), 16, 16)
        out = pipeline.apply_drc(img, {"drc": "display", "drc_strength": 1.0,
                                       "preserve_white": True})
        L = pipeline._palette_lab_lightness(out.getpixel((0, 0)))
        self.assertGreaterEqual(L, pipeline._PALETTE_WHITE_L - 2)

    def test_drc_auto_mode(self):
        img = solid((120, 130, 140), 16, 16)
        out = pipeline.apply_drc(img, {"drc": "auto", "drc_strength": 0.9})
        self.assertEqual(out.size, (16, 16))


class TestCoverageOrdered(unittest.TestCase):
    def test_solid_white(self):
        out = pipeline.dither_ordered(solid((255, 255, 255)))
        self.assertEqual(set(out), {0x0})

    def test_solid_black(self):
        out = pipeline.dither_ordered(solid((0, 0, 0)))
        self.assertEqual(set(out), {0xF})

    def test_mid_gray_reconstructs_tone(self):
        # Coverage dither's invariant: the LOCAL AVERAGE of the chosen
        # inks reconstructs the target (it solves for mixture proportions,
        # it does not snap to nearest). For mid-gray the tightest-variance
        # tetrahedron is chromatic -- every pixel stays near the target
        # brightness, which speckles less than a black/white checkerboard.
        out = pipeline.dither_ordered(solid((128, 128, 128), 64, 64))
        s = set(out)
        self.assertTrue(s <= pipeline.VALID_NIBBLES)
        self.assertGreater(len(s), 1)
        lin = pipeline._SRGB2LIN
        lum = {n: lin[r] * 0.2126 + lin[g] * 0.7152 + lin[b] * 0.0722
               for n, (r, g, b) in pipeline.PALETTE}
        avg = sum(lum[n] for n in out) / len(out)
        self.assertAlmostEqual(avg, float(lin[128]), delta=0.03)

    def test_primary_red_uses_red_ink(self):
        out = pipeline.dither_ordered(solid((220, 30, 30), 32, 32))
        self.assertIn(0x6, set(out))

    def test_full_frame_size(self):
        img = Image.new("RGB", (300, 200), (90, 140, 200))
        out = pipeline.dither_ordered(img)
        self.assertEqual(len(out), 300 * 200)
        self.assertTrue(all(n in pipeline.VALID_NIBBLES for n in out))


class TestProcessImageWithTone(unittest.TestCase):
    def test_full_frame_with_tone(self):
        img = Image.new("RGB", (800, 600), (90, 140, 200))
        frame = pipeline.process_image(img, 1200, 1600, "floyd",
                                       {"saturation": 1.2, "drc": "display"})
        self.assertEqual(len(frame), 960000)

    def test_full_frame_ordered_with_tone(self):
        img = Image.new("RGB", (800, 600), (90, 140, 200))
        frame = pipeline.process_image(img, 1200, 1600, "ordered",
                                       {"saturation": 1.2, "drc": "display"})
        self.assertEqual(len(frame), 960000)
        nibbles = [n for px in frame for n in (px >> 4, px & 0xF)]
        self.assertTrue(all(n in pipeline.VALID_NIBBLES for n in nibbles))

    def test_process_bytes_entry(self):
        img = Image.new("RGB", (64, 48), (200, 100, 50))
        buf = __import__("io").BytesIO()
        img.save(buf, "PNG")
        frame = pipeline.process(buf.getvalue(), 120, 160)
        self.assertEqual(len(frame), 120 * 160 // 2)


if __name__ == "__main__":
    unittest.main()
