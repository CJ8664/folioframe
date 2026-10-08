#include "Gdeb0709e01Panel.h"

#include <TFT_eSPI.h>
#include <qrcode.h>

#include "../ui/EinkLayout.h"
#include "../ui/EinkTheme.h"

// TFT_eSPI_ESP32_S3.h selects CS_L/CS_H with `#if TFT_CS >= 32`. A D-pin name
// evaluates to 0 there, so CS0 (GPIO44) would never be asserted.
#if !defined(TFT_CS) || TFT_CS != 44
#error "TFT_CS must be the literal GPIO number 44 (not D7); see platformio.ini"
#endif

// Old Seeed_GFX library (v1) EPaper class. Proven working on EE02 via CNX review.
// Setup 518 (7.09" GDEB0709E01) is activated via src/User_Setup.h.
static EPaper epaper;

// Convert in bands to bound working memory: 64 rows * 1200 px * 2 B.
static const int kBandRows = 64;

uint16_t Gdeb0709e01Panel::nibbleToRgb565(uint8_t nibble) {
  switch (nibble) {
    case 0x0:
      return 0xFFFF;  // white
    case 0x2:
      return 0x07E0;  // green
    case 0x6:
      return 0xF800;  // red
    case 0xB:
      return 0xFFE0;  // yellow
    case 0xD:
      return 0x001F;  // blue
    case 0xF:
      return 0x0000;  // black
    default:
      return 0x0000;  // invalid index -> black, never garbage
  }
}

bool Gdeb0709e01Panel::begin() {
  if (!psramFound()) return false;
  // The old library's setup handles EN/RST via the board config.
  // We still do belt-and-braces here.
  pinMode(43, OUTPUT);
  digitalWrite(43, HIGH);
  delay(500);
  pinMode(38, OUTPUT);
  digitalWrite(38, LOW);
  delay(200);
  digitalWrite(38, HIGH);
  delay(500);
  Serial.printf("panel pre-begin, BUSY=%d\n", digitalRead(4));
  epaper.begin();
  // Old library begin() is void; check BUSY to see if panel is alive.
  Serial.printf("panel begin ok, BUSY=%d\n", digitalRead(4));
  return true;
}

bool Gdeb0709e01Panel::drawPacked4bpp(const uint8_t* buf, size_t len) {
  PanelDims d = dims();
  const size_t expect = (size_t)d.width * d.height / 2;
  if (!buf || len != expect) return false;

  uint16_t* band =
      (uint16_t*)ps_malloc((size_t)d.width * kBandRows * sizeof(uint16_t));
  if (!band) return false;

  for (uint16_t y0 = 0; y0 < d.height; y0 += kBandRows) {
    int rows = kBandRows;
    if (y0 + rows > d.height) rows = d.height - y0;
    for (int r = 0; r < rows; r++) {
      const uint8_t* srcRow = buf + ((size_t)(y0 + r) * d.width) / 2;
      uint16_t* dstRow = band + (size_t)r * d.width;
      for (uint16_t x = 0; x < d.width; x += 2) {
        uint8_t packed = srcRow[x / 2];
        dstRow[x] = nibbleToRgb565(packed >> 4);
        dstRow[x + 1] = nibbleToRgb565(packed & 0x0F);
      }
    }
    epaper.pushImage(0, y0, d.width, rows, band);
  }
  free(band);
  epaper.update();
  return true;
}

bool Gdeb0709e01Panel::drawStatus(const char* title, const char* lines[],
                                  int numLines, bool setupHeader) {
  // Warm Clay layout per approved mockups. "FolioFrame Setup" header only
  // on setup-phase screens; post-pairing screens get the title at top.
  Serial.println("drawStatus: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();

  int titleY;
  if (setupHeader) {
    layout.header();
    layout.rule(230);
    titleY = 280;
  } else {
    // No setup header: title takes the header's position.
    titleY = 130;
  }

  // Title: 52px (font4 x2), left-aligned at x=82.
  // Post-pairing screens use 78px for the title since it's the top element.
  if (setupHeader) {
    layout.textLeft(82, titleY, title, folioframe::theme::FONT_TITLE, 2,
                    folioframe::theme::INK_BLACK);
  } else {
    layout.textLeft(80, titleY, title, folioframe::theme::FONT_TITLE, 3,
                    folioframe::theme::INK_BLACK);
  }

  // Body lines: 26px, left-aligned at x=82, 70px spacing.
  int y = titleY + 100;
  for (int i = 0; i < numLines; i++) {
    if (lines[i][0] == '\0') {
      y += 40;
      continue;
    }
    layout.textLeft(82, y, lines[i], folioframe::theme::FONT_BODY, 1,
                    folioframe::theme::INK_BLACK);
    y += 70;
  }

  layout.helpQR();

  Serial.printf("update start, BUSY=%d\n", digitalRead(4));
  uint32_t t0 = millis();
  epaper.update();
  uint32_t dt = millis() - t0;
  Serial.printf("update done in %lums, BUSY=%d\n", dt, digitalRead(4));
  if (dt < 5000 && digitalRead(4)) {
    Serial.println("WARN: refresh returned fast with BUSY high; "
                   "panel may not have executed it");
  }
  Serial.println("drawStatus: done");
  return true;
}

void Gdeb0709e01Panel::drawQRCode(const char* text, int x, int y, int size) {
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(6)];
  qrcode_initText(&qrcode, qrcodeData, 6, 0, text);

  int scale = size / qrcode.size;
  if (scale < 1) scale = 1;
  int qrSize = qrcode.size * scale;

  // White background for scannability
  epaper.fillRect(x, y, qrSize, qrSize, TFT_WHITE);

  for (uint8_t row = 0; row < qrcode.size; row++) {
    for (uint8_t col = 0; col < qrcode.size; col++) {
      if (qrcode_getModule(&qrcode, col, row)) {
        epaper.fillRect(x + col * scale, y + row * scale, scale, scale,
                        TFT_BLACK);
      }
    }
  }
}

void Gdeb0709e01Panel::drawHelpQR() {
  // Small help QR in the bottom-right corner of every non-photo status
  // screen. Drawn into the same framebuffer before the single refresh.
  static const char* kHelpUrl = "https://github.com/CJ8664/folioframe";
  // Version-6 QR = 41 modules; drawQRCode() scales to fit the target size.
  const int kTarget = 200;
  const int kModules = 41;
  const int kSize = kModules * (kTarget / kModules);  // 164 px
  const int kMargin = 48;
  const int x = 1200 - kSize - kMargin;
  const int y = 1600 - kSize - kMargin;
  drawQRCode(kHelpUrl, x, y, kTarget);
  epaper.setTextDatum(MC_DATUM);
  epaper.setTextColor(TFT_BLACK);
  epaper.drawString("Scan for help", x + kSize / 2, y - 36, 2);
  epaper.setTextDatum(TL_DATUM);
}

bool Gdeb0709e01Panel::drawSetupQR(const char* title, const char* apName,
                                   const char* url) {
  // Matches the approved setup-portal mockup EXACTLY (except typeface).
  // Header: frame icon + "FolioFrame Setup" + subtitle.
  // Clay network card with Wi-Fi icon. 3 steps with exact mockup wording.
  // Two QR cards: clay QR for setup, sage QR for GitHub. Footer.
  Serial.println("drawSetupQR: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();

  using folioframe::theme::FONT_BODY;
  using folioframe::theme::FONT_SMALL;
  using folioframe::theme::FONT_TITLE;
  using folioframe::theme::INK_BLACK;
  using folioframe::theme::INK_GREEN;
  using folioframe::theme::INK_RED;
  using folioframe::theme::INK_WHITE;

  // Header: frame icon + title + subtitle (mockup positions)
  layout.frameIcon(80, 105, 74, INK_BLACK);
  layout.textLeft(175, 110, "FolioFrame Setup", FONT_TITLE, 3, INK_BLACK);
  layout.textLeft(82, 205, "Connect your frame in three simple steps.",
                  FONT_BODY, 1, INK_BLACK);
  layout.rule(255);

  // Network card with Wi-Fi icon (icon drawn inside networkCard)
  layout.networkCard(apName);

  // Step 1 (mockup wording)
  int sy = 530;
  layout.stepCircle(111, sy, 1);
  layout.textLeft(170, sy - 30, "Join the frame's Wi-Fi", FONT_BODY, 1,
                  INK_BLACK);
  layout.textLeft(170, sy + 6, "Open Wi-Fi settings on your phone or computer",
                  FONT_SMALL, 1, INK_BLACK);
  layout.textLeft(170, sy + 28, "and select the network above.", FONT_SMALL, 1,
                  INK_BLACK);
  // Step 2
  sy += 175;
  layout.stepCircle(111, sy, 2);
  layout.textLeft(170, sy - 30, "Open the setup page", FONT_BODY, 1, INK_BLACK);
  layout.textLeft(170, sy + 6, "Scan the setup QR below, or enter", FONT_SMALL,
                  1, INK_BLACK);
  layout.textLeft(170, sy + 28, "http://192.168.4.1 in your browser.",
                  FONT_SMALL, 1, INK_RED);
  // Step 3
  sy += 175;
  layout.stepCircle(111, sy, 3);
  layout.textLeft(170, sy - 30, "Continue setup on your phone", FONT_BODY, 1,
                  INK_BLACK);
  layout.textLeft(170, sy + 6, "On the setup page, choose your home Wi-Fi",
                  FONT_SMALL, 1, INK_BLACK);
  layout.textLeft(170, sy + 28, "and enter its password to give the frame",
                  FONT_SMALL, 1, INK_BLACK);
  layout.textLeft(170, sy + 50, "internet access.", FONT_SMALL, 1, INK_BLACK);

  // QR cards with colored QRs (mockup: clay for setup, sage for GitHub)
  const int cardY = 1020;
  const int cardW = 498;
  layout.qrCard(82, cardY, cardW, "OPEN AFTER JOINING THE FRAME'S WI-FI ABOVE.",
                "Setup page", url, "http://192.168.4.1", INK_RED);
  layout.qrCard(82 + cardW + 40, cardY, cardW,
                "READ MORE ABOUT FOLIOFRAME AND ITS SOURCE.",
                "Project on GitHub", "https://github.com/CJ8664/folioframe",
                "github.com/CJ8664/spectra-frame", INK_GREEN);

  // Footer (mockup wording, centered)
  layout.textCenter(600, 1535, "Keep this screen visible until setup is complete.",
                    FONT_SMALL, 1, INK_BLACK);

  Serial.printf("update start, BUSY=%d\n", digitalRead(4));
  uint32_t t0 = millis();
  epaper.update();
  uint32_t dt = millis() - t0;
  Serial.printf("update done in %lums, BUSY=%d\n", dt, digitalRead(4));
  Serial.println("drawSetupQR: done");
  return true;
}

bool Gdeb0709e01Panel::drawPairing(const char* claimCode, const char* where) {
  // Warm Clay pairing screen per approved mockup (spectraframe-ux-pairing).
  // Measurements verified against the mockup CSS (VERIFY_EINK_UI_A.md).
  Serial.println("drawPairing: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();

  using folioframe::theme::FONT_BODY;
  using folioframe::theme::FONT_TITLE;
  using folioframe::theme::INK_BLACK;
  using folioframe::theme::INK_RED;

  // Header + title (both 75px-equivalent: font4 x3 = 78px)
  layout.header();
  layout.textCenter(600, 300, "Pair this frame", FONT_TITLE, 3, INK_BLACK);

  // Steps (48px-equivalent: font4 x2 = 52px), left-aligned at x=190
  layout.textLeft(190, 460, "1. Open your FolioFrame console", FONT_BODY, 2,
                  INK_BLACK);
  layout.textLeft(190, 520, "   in a browser", FONT_BODY, 2, INK_BLACK);
  layout.textLeft(190, 660, "2. Go to 'Pair a frame'", FONT_BODY, 2, INK_BLACK);
  layout.textLeft(190, 760, "3. Enter this code:", FONT_BODY, 2, INK_BLACK);

  // Claim code (48px, centered, red for emphasis)
  layout.textCenter(600, 860, claimCode ? claimCode : "------", FONT_BODY, 2,
                    INK_RED);

  // Server URL (48px, centered, red/rust)
  if (where && where[0] != '\0') {
    layout.textCenter(600, 1020, where, FONT_BODY, 2, INK_RED);
  }

  layout.helpQR();

  Serial.printf("update start, BUSY=%d\n", digitalRead(4));
  uint32_t t0 = millis();
  epaper.update();
  uint32_t dt = millis() - t0;
  Serial.printf("update done in %lums, BUSY=%d\n", dt, digitalRead(4));
  Serial.println("drawPairing: done");
  return true;
}

void Gdeb0709e01Panel::sleep() { epaper.sleep(); }
