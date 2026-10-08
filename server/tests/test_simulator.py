"""Tests for the display simulator (server/simulator.py)."""
import unittest

import simulator


class TestSimPanel(unittest.TestCase):
    def test_display_dimensions(self):
        p = simulator.SimPanel()
        self.assertEqual(p.img.size, (1200, 1600))

    def test_palette_values(self):
        self.assertEqual(simulator.INK_WHITE, (255, 255, 255))
        self.assertEqual(simulator.INK_BLACK, (0, 0, 0))
        self.assertEqual(simulator.INK_RED, (193, 102, 62))  # clay #c1663e
        self.assertEqual(simulator.INK_GREEN, (96, 116, 87))  # sage #607457

    def test_all_screens_render(self):
        for name, fn in simulator.SCREENS.items():
            img = fn()
            self.assertEqual(img.size, (1200, 1600),
                             f"screen {name} wrong size")

    def test_wrap_center_splits_long_words(self):
        p = simulator.SimPanel()
        # A single word longer than max_chars should not crash
        p.wrap_center(600, 100, 10, 30, "a" * 50, 24, simulator.INK_BLACK)

    def test_help_qr_renders(self):
        p = simulator.SimPanel()
        p.clear()
        p.help_qr()
        # QR area should not be blank (has black modules)
        region = p.img.crop((950, 1300, 1150, 1500))
        colors = region.getcolors(maxcolors=100000)
        self.assertTrue(colors and len(colors) > 1)

    def test_setup_screen_has_qr_cards(self):
        img = simulator.render_setup()
        # Card area should contain non-white pixels (QR modules)
        region = img.crop((82, 1000, 1118, 1470))
        colors = region.getcolors(maxcolors=1000000)
        self.assertTrue(colors and len(colors) > 2)

    def test_device_status_icons(self):
        for icon in ("checking", "download", "verifying", "success",
                     "failure", "battery", "critical_battery",
                     "wifi_lost", "wifi_weak", "photo_error"):
            img = simulator.render_device_status(icon, "Title", "Detail")
            self.assertEqual(img.size, (1200, 1600))


if __name__ == "__main__":
    unittest.main()
