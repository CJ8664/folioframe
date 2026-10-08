"""FolioFrame display simulator.

Renders the firmware's e-paper screens (StatusScreen / EinkLayout) to PIL
images without hardware. Mirrors the exact coordinates, colors, and layout
logic from src/ui/EinkLayout.cpp and src/hal/Gdeb0709e01Panel.cpp.

Hardware modeled:
  - Panel: Good Display GDEB0709E01, 1200x1600, Spectra 6
  - 6 inks: White, Black, Red (clay), Yellow (ochre), Blue, Green (sage)
  - 4bpp packed (2 px/byte) — simulated at full color depth for clarity

Usage:
  from simulator import render_device_status, render_pairing, ...
  img = render_device_status("download", "Update available", "...")
  img.save("screen.png")
"""
import math

from PIL import Image, ImageDraw, ImageFont

# --- Display geometry (from include/board_config.h) ---
DISPLAY_W = 1200
DISPLAY_H = 1600

# --- Spectra 6 palette (from src/ui/EinkTheme.h) ---
# Nibble values mapped to RGB. White/Black/Green calibrated from hardware
# photo (0.0.7). Red/Yellow/Blue use Warm Clay design tokens.
INK_WHITE = (255, 255, 255)   # 0x00 — paper
INK_BLACK = (0, 0, 0)         # 0x0F — ink
INK_RED = (193, 102, 62)      # 0x06 — clay #c1663e
INK_YELLOW = (201, 154, 63)   # 0x0B — ochre #C99A3F
INK_BLUE = (0, 0, 255)        # 0x0D — blue (unverified, avoid)
INK_GREEN = (96, 116, 87)     # 0x02 — sage #607457

# Semantic aliases (Warm Clay)
PAPER = INK_WHITE
INK = INK_BLACK
CLAY = INK_RED
SAGE = INK_GREEN
OCHRE = INK_YELLOW


class SimPanel:
    """Software implementation of the Panel HAL. Records drawing operations
    on a 1200x1600 PIL canvas using the Spectra 6 palette."""

    def __init__(self):
        self.img = Image.new("RGB", (DISPLAY_W, DISPLAY_H), PAPER)
        self.draw = ImageDraw.Draw(self.img)
        # Font scaling: firmware uses TFT_eSPI fonts at various textSize.
        # We approximate with DejaVu at scaled point sizes.
        self._font_cache = {}

    def _font(self, size_px):
        if size_px not in self._font_cache:
            try:
                f = ImageFont.truetype("DejaVuSans.ttf", size_px)
            except OSError:
                f = ImageFont.load_default()
            self._font_cache[size_px] = f
        return self._font_cache[size_px]

    # --- Primitives (mirror TFT_eSPI API used by EinkLayout) ---

    def clear(self):
        self.draw.rectangle([0, 0, DISPLAY_W, DISPLAY_H], fill=PAPER)

    def fill_rect(self, x, y, w, h, color):
        self.draw.rectangle([x, y, x + w - 1, y + h - 1], fill=color)

    def fill_round_rect(self, x, y, w, h, r, color):
        self.draw.rounded_rectangle([x, y, x + w - 1, y + h - 1],
                                    radius=r, fill=color)

    def draw_round_rect(self, x, y, w, h, r, color):
        self.draw.rounded_rectangle([x, y, x + w - 1, y + h - 1],
                                    radius=r, outline=color, width=2)

    def fill_circle(self, cx, cy, r, color):
        self.draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)

    def draw_circle(self, cx, cy, r, color, width=2):
        self.draw.ellipse([cx - r, cy - r, cx + r, cy + r],
                          outline=color, width=width)

    def draw_line(self, x0, y0, x1, y1, color, width=2):
        self.draw.line([x0, y0, x1, y1], fill=color, width=width)

    def draw_rect(self, x, y, w, h, color, width=2):
        self.draw.rectangle([x, y, x + w - 1, y + h - 1],
                            outline=color, width=width)

    def draw_triangle(self, x0, y0, x1, y1, x2, y2, color, width=2):
        self.draw.polygon([x0, y0, x1, y1, x2, y2],
                          outline=color, width=width)

    def text_center(self, cx, y, text, size_px, color):
        """Centered text (MC_DATUM equivalent: centered horizontally AND
        vertically on (cx, y))."""
        font = self._font(size_px)
        bbox = self.draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        self.draw.text((cx - tw / 2, y - th / 2 - bbox[1]), text,
                       font=font, fill=color)

    def text_left(self, x, y, text, size_px, color):
        """Left-aligned text (TL_DATUM equivalent)."""
        font = self._font(size_px)
        self.draw.text((x, y), text, font=font, fill=color)

    def wrap_center(self, cx, y, max_chars, line_height, text,
                    size_px, color):
        """Word-wrap and center each line (mirrors EinkLayout::wrapCenter).

        Splits overlong words across lines like the firmware does.
        """
        if not text or max_chars <= 0:
            return
        max_chars = min(max_chars, 90)
        words = text.split()
        line = ""
        for word in words:
            # Split a single word exceeding max_chars (firmware does this)
            while len(word) > max_chars:
                if line:
                    self.text_center(cx, y, line, size_px, color)
                    y += line_height
                    line = ""
                self.text_center(cx, y, word[:max_chars], size_px, color)
                y += line_height
                word = word[max_chars:]
            test = (line + " " + word).strip()
            if len(test) > max_chars and line:
                self.text_center(cx, y, line, size_px, color)
                y += line_height
                line = word
            else:
                line = test
        if line:
            self.text_center(cx, y, line, size_px, color)

    # --- Layout components (mirror EinkLayout methods) ---

    def status_backdrop(self):
        """Warm Clay backdrop: red rounded rect + green circle with
        halftone white bands (mirrors drawBackdrop)."""
        self._draw_backdrop(-420, 410, 1275, 1425)

    def setup_backdrop(self):
        self._draw_backdrop(-280, 190, 1245, 1075)

    def _draw_backdrop(self, clay_x, clay_y, sage_cx, sage_cy):
        clay_w, clay_h = 920, 560
        sage_r = 425
        # Clay rounded rect
        self.fill_round_rect(clay_x, clay_y, clay_w, clay_h, 170, CLAY)
        # Halftone bands on clay
        for y in range(clay_y + 4, clay_y + clay_h, 8):
            self.fill_rect(0, y, clay_x + clay_w, 3, PAPER)
        # Sage circle
        self.fill_circle(sage_cx, sage_cy, sage_r, SAGE)
        # Halftone bands on sage
        sage_left = sage_cx - sage_r
        for y in range(sage_cy - sage_r, DISPLAY_H, 8):
            self.fill_rect(sage_left, y, DISPLAY_W - sage_left, 1, PAPER)

    def wordmark(self):
        # textCenter(600,166,"F O L I O F R A M E",FONT_SMALL,2) = 32px
        self.text_center(600, 166, "F O L I O F R A M E", 32, CLAY)

    def status_icon(self, icon):
        """Draw status icon at (600, 485), r=105 (mirrors statusIcon)."""
        cx, cy = 600, 485
        self.fill_circle(cx, cy, 105, PAPER)
        self.draw_circle(cx, cy, 105, INK)
        self.draw_circle(cx, cy, 103, INK)
        accent = SAGE if icon == "success" else CLAY

        if icon == "checking":
            self.draw_circle(cx, cy, 50, accent)
            self.fill_rect(cx + 28, cy - 54, 35, 28, PAPER)
            self.draw_line(cx + 41, cy - 46, cx + 62, cy - 46, accent)
            self.draw_line(cx + 62, cy - 46, cx + 62, cy - 25, accent)
            self.draw_line(cx, cy, cx, cy - 31, INK)
            self.draw_line(cx, cy, cx + 25, cy + 13, INK)
        elif icon == "download":
            self.draw_round_rect(cx - 46, cy - 40, 92, 75, 8, accent)
            self.draw_line(cx, cy - 62, cx, cy + 16, accent)
            self.draw_line(cx - 29, cy - 12, cx, cy + 17, accent)
            self.draw_line(cx + 29, cy - 12, cx, cy + 17, accent)
            self.draw_line(cx - 54, cy + 58, cx + 54, cy + 58, accent)
        elif icon == "verifying":
            pts = [(0, -68), (49, -48), (43, 16), (0, 64),
                   (-43, 16), (-49, -48)]
            for i in range(len(pts)):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % len(pts)]
                self.draw_line(cx + x0, cy + y0, cx + x1, cy + y1, accent)
            self.draw_line(cx - 24, cy, cx - 5, cy + 20, accent)
            self.draw_line(cx - 5, cy + 20, cx + 31, cy - 22, accent)
        elif icon == "success":
            self.draw_circle(cx, cy, 57, accent)
            self.draw_line(cx - 31, cy, cx - 8, cy + 24, accent, width=4)
            self.draw_line(cx - 8, cy + 24, cx + 37, cy - 27, accent, width=4)
        elif icon == "failure":
            self.draw_circle(cx, cy, 57, accent)
            self.draw_line(cx - 25, cy - 25, cx + 25, cy + 25, accent, width=4)
            self.draw_line(cx + 25, cy - 25, cx - 25, cy + 25, accent, width=4)
        elif icon == "battery":
            self.draw_round_rect(cx - 58, cy - 34, 110, 68, 8, accent)
            self.fill_rect(cx + 52, cy - 15, 12, 30, accent)
            self.fill_rect(cx - 46, cy - 22, 63, 44, accent)
        elif icon == "critical_battery":
            self.draw_triangle(cx, cy - 65, cx - 69, cy + 54,
                               cx + 69, cy + 54, accent, width=3)
            self.draw_line(cx, cy - 24, cx, cy + 15, accent, width=4)
            self.fill_circle(cx, cy + 35, 4, accent)
        elif icon in ("wifi_lost", "wifi_weak"):
            self._wifi_icon(cx, cy + 18, 112, accent)
            if icon == "wifi_lost":
                self.draw_line(cx - 58, cy - 58, cx + 58, cy + 58, INK, width=4)
                self.draw_line(cx + 58, cy - 58, cx - 58, cy + 58, INK, width=4)
        elif icon == "photo_error":
            self.draw_round_rect(cx - 61, cy - 48, 122, 96, 8, accent)
            self.fill_circle(cx + 28, cy - 22, 9, accent)
            self.draw_line(cx - 43, cy + 30, cx - 9, cy - 4, accent)
            self.draw_line(cx - 9, cy - 4, cx + 10, cy + 15, accent)
            self.draw_line(cx + 10, cy + 15, cx + 30, cy - 3, accent)
            self.draw_line(cx + 30, cy - 3, cx + 44, cy + 11, accent)

    def _wifi_icon(self, cx, cy, size, color):
        r = size // 2
        self.fill_circle(cx, cy, r // 5, color)
        for i in range(1, 4):
            ar = (r * i) // 3
            for a in range(200, 341, 3):
                rad = math.radians(a)
                px = cx + int(ar * math.cos(rad))
                py = cy + int(ar * math.sin(rad)) - r // 4
                self.fill_circle(px, py, 2, color)

    def _frame_icon(self, x, y, size, color):
        """Picture frame icon (mirrors EinkLayout::frameIcon)."""
        t = max(size // 10, 4)
        for i in range(t):
            self.draw_rect(x + i, y + i, size - 2 * i, size - 2 * i, color)
        inset = size // 3
        self.draw_rect(x + inset, y + inset, size - 2 * inset,
                       size - 2 * inset, color)
        c = size // 8
        self.fill_rect(x, y, c, c, color)
        self.fill_rect(x + size - c, y, c, c, color)
        self.fill_rect(x, y + size - c, c, c, color)
        self.fill_rect(x + size - c, y + size - c, c, c, color)

    def _step_circle(self, cx, y, n):
        """Numbered step circle (mirrors EinkLayout::stepCircle).

        Number: FONT_BODY x1 = 26px.
        """
        self.fill_circle(cx, y, 29, PAPER)
        self.draw_circle(cx, y, 29, CLAY)
        self.draw_circle(cx, y, 28, CLAY)
        self.text_center(cx, y, str(n), 26, CLAY)

    def _network_card(self, ap_name):
        """Clay Wi-Fi network card (mirrors EinkLayout::networkCard).

        AP name: FONT_BODY x1 = 26px.
        """
        self.fill_round_rect(82, 326, 1036, 132, 18, CLAY)
        for y in range(334, 450, 8):
            self.fill_rect(100, y, 1000, 2, PAPER)
        self.draw_round_rect(82, 326, 1036, 132, 18, PAPER)
        self._wifi_icon(170, 392, 56, PAPER)
        self.text_center(640, 379, ap_name, 26, PAPER)

    def _qr_card(self, x, y, w, label, heading, qr_text, url, qr_color):
        """QR card with heading, label, QR, and URL (mirrors qrCard).

        Heading: FONT_BODY x1 = 26px. Label/URL: FONT_SMALL x1 = 16px.
        """
        h = 470
        self.fill_rect(x, y, w, h, PAPER)
        self.draw_round_rect(x, y, w, h, 12, INK)
        cy = y + 24
        self.text_center(x + w // 2, cy, heading, 26, INK)
        cy += 38
        self.text_center(x + w // 2, cy, label, 16, SAGE)
        cy += 34
        qr_size = 248
        qr_x = x + (w - qr_size) // 2
        self._draw_qr(qr_text, qr_x, cy, qr_size, qr_color)
        cy += qr_size + 20
        self.text_center(x + w // 2, cy, url, 16, CLAY)

    def progress_bar(self, percent):
        """Progress bar at (240, 1067), 720x30 (mirrors progressBar).

        Labels: FONT_SMALL x2 = 32px.
        """
        percent = min(percent, 100)
        x, label_y, y, w, h = 240, 1010, 1067, 720, 30
        self.text_left(x, label_y, "Downloading", 32, INK)
        label = f"{percent}%"
        font = self._font(32)
        bbox = self.draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        self.draw.text((x + w - tw, label_y), label, font=font, fill=INK)
        self.draw_round_rect(x, y, w, h, 15, CLAY)
        inner = (w - 8) * percent // 100
        if inner > 0:
            self.fill_rect(x + 4, y + 4, inner, h - 8, CLAY)

    def help_qr(self, target_size=296, right=76, bottom=64):
        """Help QR in bottom-right corner (mirrors helpQR).

        Firmware defaults (EinkLayout.h): (296, 76, 64).
        Callers may override, e.g. drawDeviceStatus/drawPairing use (185,52,42).

        Firmware centers the QR modules within the target area:
        x + (target_size - qr_size) / 2, caption at y + qr_size + 16.
        """
        url = "https://github.com/CJ8664/folioframe"
        caption_space = 34 if target_size <= 200 else 40
        modules = 41
        qr_size = modules * (target_size // modules)
        x = DISPLAY_W - right - target_size
        y = DISPLAY_H - bottom - target_size - caption_space
        # Center the QR grid within the target area (firmware does this)
        qx = x + (target_size - qr_size) // 2
        self._draw_qr(url, qx, y, target_size, INK)
        # Caption: FONT_SMALL x1 = 16px
        self.text_center(x + target_size // 2, y + qr_size + 16,
                         "Scan for help", 16, INK)

    def _draw_qr(self, text, x, y, target_size, color):
        """Draw QR code (uses qrcode lib; falls back to text if too long).

        Mirrors firmware: text exceeding version-6 capacity renders as
        red text instead of a garbage QR.
        """
        try:
            import qrcode as qr_lib
            from qrcode.exceptions import DataOverflowError
            qr = qr_lib.QRCode(version=6, error_correction=qr_lib.ERROR_CORRECT_L,
                               box_size=1, border=0)
            qr.add_data(text)
            qr.make(fit=False)
            modules = qr.modules
            size = len(modules)
        except ImportError:
            # qrcode lib not installed: text fallback
            self.text_center(x + target_size // 2, y + target_size // 2,
                             text[:40], 20, CLAY)
            return
        except Exception:
            # DataOverflowError (text too long) or other QR failure:
            # firmware draws the URL as red text
            self.text_center(x + target_size // 2, y + target_size // 2,
                             text[:60], 20, CLAY)
            return
        scale = max(target_size // size, 1)
        qr_size = size * scale
        # White background
        self.fill_rect(x, y, qr_size, qr_size, PAPER)
        for r in range(size):
            for c in range(size):
                if modules[r][c]:
                    self.fill_rect(x + c * scale, y + r * scale,
                                   scale, scale, color)


# --- Screen renderers (mirror StatusScreen methods) ---

def render_device_status(icon, title, detail, footer=None, progress=None):
    """Mirror Gdeb0709e01Panel::drawDeviceStatus exactly.

    Font sizes: FONT_TITLE x3 = 78px, FONT_SMALL x2 = 32px, FONT_SMALL x1 = 16px.
    """
    p = SimPanel()
    p.clear()
    p.status_backdrop()
    p.wordmark()
    p.status_icon(icon)
    # Title at (600, 723) 78px, detail at (600, 904) 32px
    p.wrap_center(600, 723, 24, 86, title, 78, INK)
    p.wrap_center(600, 904, 48, 48, detail, 32, INK)
    if progress is not None:
        p.progress_bar(progress)
        if footer:
            p.wrap_center(600, 1190, 48, 42, footer, 32, INK)
    elif footer:
        p.wrap_center(600, 1084, 48, 42, footer, 32, INK)
    p.help_qr(185, 52, 42)
    return p.img


def render_status(title, lines, setup_header=False):
    """Mirror Gdeb0709e01Panel::drawStatus exactly.

    No backdrop, no wordmark — just clear(). Title left-aligned:
    78px at (80,130), or 52px at (82,280) with setup header.
    Body: 26px left-aligned at x=82, 70px spacing from titleY+100.
    helpQR() with firmware defaults (296, 76, 64).
    """
    p = SimPanel()
    p.clear()

    if setup_header:
        # header() + rule(230), title 52px at (82, 280)
        p.text_left(80, 130, "FolioFrame Setup", 78, INK)
        p.fill_rect(82, 230, 1036, 2, INK)
        title_y = 280
        p.text_left(82, title_y, title, 52, INK)
    else:
        title_y = 130
        p.text_left(80, title_y, title, 78, INK)

    y = title_y + 100
    for line in lines:
        if not line:
            y += 40
            continue
        p.text_left(82, y, line, 26, INK)
        y += 70

    p.help_qr()  # firmware defaults: (296, 76, 64)
    return p.img


def render_pairing(claim_code="AB12-CD34", where="frame.chiragjain.info"):
    """Mirror Gdeb0709e01Panel::drawPairing exactly.

    Layout per folioframe-device-mockups.html (Frosted Glass):
    frameIcon(80,130,74), "FolioFrame Setup" 78px at (175,130),
    "Pair this frame" 52px at (190,300), three steps 32px at x=190
    y=480/610/735, claim-code box (190,823,820,155) centered at y=900,
    code 78px at (600,900), URL 32px at (600,1080), helpQR defaults (296,76,64).
    """
    p = SimPanel()
    p.clear()
    p.status_backdrop()
    p._frame_icon(80, 130, 74, SAGE)
    p.text_left(175, 130, "FolioFrame Setup", 78, INK)
    p.text_left(190, 300, "Pair this frame", 52, INK)
    p.text_left(190, 480, "1. Open your FolioFrame console in a browser",
                32, INK)
    p.text_left(190, 610, "2. Go to 'Pair a frame'", 32, INK)
    p.text_left(190, 735, "3. Enter this code:", 32, INK)

    # Claim-code box: centered at y=900
    p.fill_round_rect(190, 823, 820, 155, 20, PAPER)
    p.draw_round_rect(190, 823, 820, 155, 20, CLAY)
    p.text_center(600, 900, claim_code or "------", 78, CLAY)

    if where:
        p.wrap_center(600, 1080, 40, 38, where, 32, CLAY)

    p.help_qr()  # firmware defaults: (296, 76, 64)
    return p.img


def render_setup(ap_name="FF-Setup-ff-e4254d8fee68",
                 url="http://192.168.4.1"):
    """Mirror Gdeb0709e01Panel::drawSetupQR exactly."""
    p = SimPanel()
    p.clear()
    p.setup_backdrop()
    setup_url = url or "http://192.168.4.1"

    # Header: frame icon + title + subtitle
    p._frame_icon(80, 130, 74, SAGE)
    p.text_left(175, 130, "FolioFrame Setup", 78, INK)
    p.text_left(82, 224, "Connect your frame in three simple steps.", 26, INK)
    p.fill_rect(82, 285, 1036, 2, INK)

    # Network card (clay, with Wi-Fi icon and AP name)
    p._network_card(ap_name)

    # Step 1 (FONT_BODY x1 = 26px)
    sy = 560
    p._step_circle(111, sy, 1)
    p.text_left(170, sy - 30, "Join the frame's Wi-Fi", 26, INK)
    p.text_left(170, sy + 6, "Open Wi-Fi settings on your phone or computer",
                26, INK)
    p.text_left(170, sy + 28, "and select the network above.", 26, INK)
    # Step 2
    sy += 150
    p._step_circle(111, sy, 2)
    p.text_left(170, sy - 30, "Open the setup page", 26, INK)
    p.text_left(170, sy + 6, "Scan the setup QR below, or enter", 26, INK)
    p.text_left(170, sy + 28, f"{setup_url} in your browser.", 26, CLAY)
    # Step 3
    sy += 150
    p._step_circle(111, sy, 3)
    p.text_left(170, sy - 30, "Continue setup on your phone", 26, INK)
    p.text_left(170, sy + 6, "On the setup page, choose your home Wi-Fi",
                26, INK)
    p.text_left(170, sy + 28, "and enter its password to give the frame",
                26, INK)
    p.text_left(170, sy + 50, "internet access.", 26, INK)

    # QR cards (heading 26px, label 16px, URL 16px)
    p._qr_card(82, 1000, 503,
               "OPEN AFTER JOINING THE FRAME'S WI-FI ABOVE.",
               "Setup page", setup_url, setup_url, CLAY)
    p._qr_card(82 + 503 + 30, 1000, 503,
               "READ MORE ABOUT FOLIOFRAME AND ITS SOURCE.",
               "Project on GitHub", "https://github.com/CJ8664/folioframe",
               "github.com/CJ8664/folioframe", SAGE)

    # Footer (FONT_SMALL x1 = 16px)
    p.text_center(600, 1535, "Keep this screen visible until setup is complete.",
                  16, INK)
    return p.img


# --- Screen registry for web UI ---
SCREENS = {
    "pairing": lambda: render_pairing("AB12-CD34"),
    "paired": lambda: render_status("FolioFrame",
                                    ["Paired!", "", "Fetching first image..."]),
    "portal": lambda: render_setup(),
    "settings": lambda: render_status("Frame settings",
                                      ["On your phone or computer,",
                                       "open this address:",
                                       "http://192.168.1.42", "",
                                       "to configure this frame."]),
    "ota_checking": lambda: render_device_status(
        "checking", "Checking for update...", "This takes a moment."),
    "ota_uptodate": lambda: render_status(
        "Software update",
        ["You're up to date.", "", "Going back to sleep."]),
    "ota_available": lambda: render_device_status(
        "download", "Update available",
        "Version v0.0.13 is ready to install.",
        "KEY2: Install now   KEY1: Skip for now"),
    "ota_progress": lambda: render_device_status(
        "download", "Downloading update...",
        "Keep the frame powered on.", progress=65),
    "ota_verifying": lambda: render_device_status(
        "verifying", "Verifying update...",
        "Making sure the download arrived complete and correct."),
    "ota_done": lambda: render_device_status(
        "success", "Update complete.",
        "Restarting with the new version..."),
    "ota_failed": lambda: render_device_status(
        "failure", "The update didn't install.",
        "Keeping your current version -- the frame will try again later.",
        "Details: checksum mismatch"),
    "ota_battery_low": lambda: render_device_status(
        "critical_battery", "Battery too low to update.",
        "Plug in USB to charge, then try again."),
    "low_battery": lambda: render_device_status(
        "battery", "Battery low.",
        "42% battery left. Showing photos as usual -- please charge soon."),
    "critical_battery": lambda: render_device_status(
        "critical_battery", "Battery critically low.",
        "Connect USB power. Skipping Wi-Fi and going to sleep to save power."),
    "wifi_lost": lambda: render_device_status(
        "wifi_lost", "Wi-Fi connection lost.",
        "Press KEY1 to open settings. We'll retry Wi-Fi later."),
    "wifi_weak": lambda: render_device_status(
        "wifi_weak", "Wi-Fi signal is weak.",
        "Move the frame closer to your router if new photos take longer."),
    "render_error": lambda: render_device_status(
        "photo_error", "This photo didn't load.",
        "Keeping the last photo -- we'll try again on the next wake."),
    "error": lambda: render_status(
        "Connection failed",
        ["Could not reach the server.", "", "Will retry on next wake."]),
}
