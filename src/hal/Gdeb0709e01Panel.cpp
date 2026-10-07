#include "Gdeb0709e01Panel.h"

#include <TFT_eSPI.h>
#include <qrcode.h>

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
                                  int numLines) {
  Serial.println("drawStatus: fillScreen");
  // Warm Clay light theme: warm white background, charcoal text.
  // Panel is 1200x1600 portrait. Font 4 is used throughout (fonts 6/8 have
  // rendering issues on this driver).
  epaper.fillScreen(TFT_WHITE);
  Serial.println("drawStatus: drawString");

  // Title: centered, charcoal
  epaper.setTextColor(TFT_BLACK);
  epaper.setTextDatum(MC_DATUM);  // Middle-Center datum for easy centering

  int y = 300;
  epaper.drawString(title, 600, y, 4);
  y += 100;

  // Subtitle lines: centered
  for (int i = 0; i < numLines; i++) {
    if (lines[i][0] == '\0') {
      y += 40;  // Extra spacing for blank lines
      continue;
    }
    epaper.drawString(lines[i], 600, y, 4);
    y += 70;
  }

  epaper.setTextDatum(TL_DATUM);  // Reset to top-left
  drawHelpQR();  // bottom-right help QR, same single refresh (no extra update)
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
  // Warm Clay light theme: warm white background, charcoal text.
  // QR code for the portal URL. Panel is 1200x1600 portrait.
  // Font 4 is used throughout (fonts 6/8 have rendering issues on this driver).
  Serial.println("drawSetupQR: fillScreen");
  epaper.fillScreen(TFT_WHITE);

  epaper.setTextColor(TFT_BLACK);
  epaper.setTextDatum(MC_DATUM);

  // Title
  int y = 180;
  epaper.drawString("FolioFrame Setup", 600, y, 4);
  y += 100;

  // Two QR codes side by side: the setup portal URL and the GitHub
  // help page (matches the reviewed mockups).
  const int kQrTarget = 340;
  const int kQrActual = 41 * (kQrTarget / 41);  // version-6 QR, 328 px
  const int kQrGap = 80;
  const int kLeftX = 600 - kQrActual - kQrGap / 2;
  const int kRightX = 600 + kQrGap / 2;
  drawQRCode(url, kLeftX, y, kQrTarget);
  drawQRCode("https://github.com/CJ8664/folioframe", kRightX, y, kQrTarget);
  y += kQrActual + 40;
  epaper.drawString("Setup page", kLeftX + kQrActual / 2, y, 4);
  epaper.drawString("Help & docs", kRightX + kQrActual / 2, y, 4);
  y += 100;

  // Instructions
  epaper.drawString("1. Join Wi-Fi network:", 600, y, 4);
  y += 70;
  epaper.drawString(apName, 600, y, 4);
  y += 70;
  epaper.drawString("2. Scan the setup QR", 600, y, 4);
  y += 70;
  epaper.drawString("3. Enter Wi-Fi details", 600, y, 4);

  epaper.setTextDatum(TL_DATUM);
  Serial.printf("update start, BUSY=%d\n", digitalRead(4));
  uint32_t t0 = millis();
  epaper.update();
  uint32_t dt = millis() - t0;
  Serial.printf("update done in %lums, BUSY=%d\n", dt, digitalRead(4));
  Serial.println("drawSetupQR: done");
  return true;
}

void Gdeb0709e01Panel::sleep() { epaper.sleep(); }
