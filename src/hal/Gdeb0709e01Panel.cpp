#include "Gdeb0709e01Panel.h"

#include <TFT_eSPI.h>

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
  epaper.fillScreen(TFT_WHITE);
  Serial.println("drawStatus: drawString");
  int y = 60;
  epaper.drawString(title, 60, y, 4);
  y += 80;
  for (int i = 0; i < numLines; i++) {
    epaper.drawString(lines[i], 60, y, 2);
    y += 48;
  }
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

void Gdeb0709e01Panel::sleep() { epaper.sleep(); }
