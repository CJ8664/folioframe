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
  // After init the panel should be idle (BUSY low). If BUSY is stuck high,
  // the panel isn't responding (disconnected FPC?) — report failure so
  // main.cpp can show the error screen instead of failing silently.
  delay(100);
  int busy = digitalRead(4);
  Serial.printf("panel begin ok, BUSY=%d\n", busy);
  if (busy) {
    Serial.println("panel begin FAILED: BUSY stuck high");
    return false;
  }
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

bool Gdeb0709e01Panel::drawDeviceStatus(PanelStatusIcon icon,
                                        const char* title,
                                        const char* detail,
                                        const char* footer,
                                        uint8_t progress,
                                        bool showProgress) {
  Serial.println("drawDeviceStatus: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();
  layout.statusBackdrop();
  layout.wordmark();
  layout.statusIcon(icon);
  layout.wrapCenter(600, 723, 24, 86, title, folioframe::theme::FONT_TITLE, 3,
                    folioframe::theme::INK_BLACK);
  layout.wrapCenter(600, 904, 48, 48, detail, folioframe::theme::FONT_SMALL, 2,
                    folioframe::theme::INK_BLACK);

  if (showProgress) {
    layout.progressBar(progress);
    if (footer) {
      layout.wrapCenter(600, 1190, 48, 42, footer,
                        folioframe::theme::FONT_SMALL, 2,
                        folioframe::theme::INK_BLACK);
    }
  } else if (footer) {
    layout.wrapCenter(600, 1084, 48, 42, footer,
                      folioframe::theme::FONT_SMALL, 2,
                      folioframe::theme::INK_BLACK);
  }
  layout.helpQR(185, 52, 42);

  uint32_t t0 = millis();
  epaper.update();
  uint32_t dt = millis() - t0;
  Serial.printf("drawDeviceStatus: update completed in %lums\n", dt);
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
  // qrcode_initText returns 0 if the text exceeds version-6 capacity.
  // Without this check, qrcode.size stays 0 and `size / qrcode.size`
  // is a division by zero -> CPU exception -> reboot.
  if (!qrcode_initText(&qrcode, qrcodeData, 6, 0, text)) return;

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

bool Gdeb0709e01Panel::drawSetupQR(const char* title, const char* apName,
                                   const char* url) {
  // Follow the setup-portal mockup's native 1200x1600 geometry and copy.
  // Opaque Spectra 6 inks approximate the mockup's translucent surfaces.
  Serial.println("drawSetupQR: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();
  layout.setupBackdrop();

  using folioframe::theme::FONT_BODY;
  using folioframe::theme::FONT_SMALL;
  using folioframe::theme::FONT_TITLE;
  using folioframe::theme::INK_BLACK;
  using folioframe::theme::INK_GREEN;
  using folioframe::theme::INK_RED;
  using folioframe::theme::INK_WHITE;

  const char* setupUrl = (url && url[0]) ? url : "http://192.168.4.1";
  char setupUrlInstruction[160];
  snprintf(setupUrlInstruction, sizeof(setupUrlInstruction),
           "%s in your browser.", setupUrl);

  // Header: frame icon + title + subtitle (mockup positions)
  layout.frameIcon(80, 130, 74, INK_GREEN);
  layout.textLeft(175, 130,
                  (title && title[0]) ? title : "FolioFrame Setup",
                  FONT_TITLE, 3, INK_BLACK);
  layout.textLeft(82, 224, "Connect your frame in three simple steps.",
                  FONT_BODY, 1, INK_BLACK);
  layout.rule(285);

  // Network card with Wi-Fi icon (icon drawn inside networkCard)
  layout.networkCard(apName);

  // Step 1 (mockup wording)
  int sy = 560;
  layout.stepCircle(111, sy, 1);
  layout.textLeft(170, sy - 30, "Join the frame's Wi-Fi", FONT_BODY, 1,
                  INK_BLACK);
  layout.textLeft(170, sy + 6, "Open Wi-Fi settings on your phone or computer",
                  FONT_BODY, 1, INK_BLACK);
  layout.textLeft(170, sy + 28, "and select the network above.", FONT_BODY, 1,
                  INK_BLACK);
  // Step 2
  sy += 150;
  layout.stepCircle(111, sy, 2);
  layout.textLeft(170, sy - 30, "Open the setup page", FONT_BODY, 1, INK_BLACK);
  layout.textLeft(170, sy + 6, "Scan the setup QR below, or enter", FONT_BODY,
                  1, INK_BLACK);
  layout.textLeft(170, sy + 28, setupUrlInstruction, FONT_BODY, 1, INK_RED);
  // Step 3
  sy += 150;
  layout.stepCircle(111, sy, 3);
  layout.textLeft(170, sy - 30, "Continue setup on your phone", FONT_BODY, 1,
                  INK_BLACK);
  layout.textLeft(170, sy + 6, "On the setup page, choose your home Wi-Fi",
                  FONT_BODY, 1, INK_BLACK);
  layout.textLeft(170, sy + 28, "and enter its password to give the frame",
                  FONT_BODY, 1, INK_BLACK);
  layout.textLeft(170, sy + 50, "internet access.", FONT_BODY, 1, INK_BLACK);

  // QR cards with colored QRs (mockup: clay for setup, sage for GitHub)
  const int cardY = 1000;
  const int cardW = 503;
  layout.qrCard(82, cardY, cardW, "OPEN AFTER JOINING THE FRAME'S WI-FI ABOVE.",
                "Setup page", setupUrl, setupUrl, INK_RED);
  layout.qrCard(82 + cardW + 30, cardY, cardW,
                "READ MORE ABOUT FOLIOFRAME AND ITS SOURCE.",
                "Project on GitHub", "https://github.com/CJ8664/folioframe",
                "github.com/CJ8664/folioframe", INK_GREEN);

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
  // Warm Clay pairing screen per approved mockup (folioframe-device-mockups.html,
  // Frosted Glass section). All elements left-aligned at x=190 except the
  // claim code (centered) and URL (centered).
  // Mockup: title 56px@300, steps 39px@480/610/735, code 78px@900,
  // URL 37px@1080, helpQR 296px@(76,64).
  // Firmware font system: 52px (font4x2) is closest to 56px; 32px (font2x2)
  // is closest to 39px/37px.
  Serial.println("drawPairing: layout");
  folioframe::EinkLayout layout(&epaper);
  layout.clear();

  using folioframe::theme::FONT_BODY;
  using folioframe::theme::FONT_SMALL;
  using folioframe::theme::FONT_TITLE;
  using folioframe::theme::INK_BLACK;
  using folioframe::theme::INK_RED;

  layout.statusBackdrop();
  layout.frameIcon(80, 130, 74, folioframe::theme::INK_GREEN);
  layout.textLeft(175, 130, "FolioFrame Setup", FONT_TITLE, 3, INK_BLACK);
  // Title: 52px (closest to mockup 56px), left-aligned at x=190, y=300.
  layout.textLeft(190, 300, "Pair this frame", FONT_TITLE, 2, INK_BLACK);
  // Steps: 32px (closest to mockup 39px), left-aligned at x=190.
  layout.textLeft(190, 480, "1. Open your FolioFrame console in a browser",
                  folioframe::theme::FONT_SMALL, 2, INK_BLACK);
  layout.textLeft(190, 610, "2. Go to 'Pair a frame'",
                  folioframe::theme::FONT_SMALL, 2, INK_BLACK);
  layout.textLeft(190, 735, "3. Enter this code:",
                  folioframe::theme::FONT_SMALL, 2, INK_BLACK);

  // Claim-code box: centered vertically at y=900 (mockup top:900px with
  // translateY(-50%)). Box height 155 -> top = 900 - 77 = 823.
  epaper.fillRoundRect(190, 823, 820, 155, 20,
                       folioframe::theme::INK_WHITE);
  epaper.drawRoundRect(190, 823, 820, 155, 20, folioframe::theme::INK_RED);
  layout.textCenter(600, 900, claimCode ? claimCode : "------", FONT_BODY, 3,
                    INK_RED);

  // Server URL: centered at y=1080, 32px (closest to mockup 37px).
  if (where && where[0] != '\0') {
    layout.wrapCenter(600, 1080, 40, 38, where,
                      folioframe::theme::FONT_SMALL, 2, INK_RED);
  }

  // Help QR: mockup specifies 296px at (76, 64) — use firmware defaults.
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
