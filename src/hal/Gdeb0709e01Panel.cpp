#include "Gdeb0709e01Panel.h"

#include <Seeed_GFX.h>

// Official product target for the 7.09" Spectra 6 panel (added Sep 2026).
// Compile will fail here if Seeed renames it — that is intentional.
static Seeed_GFX display(Seeed_Product::Seeed_ePaper_7INCH09_C);

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
  // Belt-and-braces power/reset: the library should drive EN (GPIO43) and
  // RST (GPIO38), but if the panel is unresponsive we ensure it ourselves.
  // EN high = panel power on; RST low pulse = hardware reset. Generous
  // delays: the panel needs time for its power regulator and controller
  // to stabilize before accepting commands.
  pinMode(43, OUTPUT);
  digitalWrite(43, HIGH);
  delay(500);
  pinMode(38, OUTPUT);
  digitalWrite(38, LOW);
  delay(200);
  digitalWrite(38, HIGH);
  delay(500);
  Serial.printf("panel pre-begin, BUSY=%d\n", digitalRead(4));
  // Do NOT ignore begin()'s result: a failed init makes every later draw a
  // silent no-op, which looks exactly like a dead panel.
  if (!display.begin()) {
    Serial.printf("panel begin failed: %s\n", display.lastResult().message);
    return false;
  }
  // BUSY (GPIO4) is the only signal back from the panel. Sample it here:
  // a live panel idles HIGH and pulls LOW while refreshing. Stuck HIGH
  // through a refresh means the panel never executed it (power/cable).
  Serial.printf("panel begin ok, BUSY=%d\n", digitalRead(4));
  return true;
}

bool Gdeb0709e01Panel::drawPacked4bpp(const uint8_t* buf, size_t len) {
  PanelDims d = dims();
  const size_t expect = (size_t)d.width * d.height / 2;
  if (!buf || len != expect) return false;  // refuse to paint garbage

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
    display.pushImage(0, y0, d.width, rows, band);
  }
  free(band);
  display.update();  // full refresh (~30 s on Spectra 6)
  return true;
}

bool Gdeb0709e01Panel::drawStatus(const char* title, const char* lines[],
                                  int numLines) {
  Serial.println("drawStatus: fillScreen");
  display.fillScreen(0xFFFF);
  Serial.println("drawStatus: drawString");
  int y = 60;
  display.drawString(title, 60, y, 4);
  y += 80;
  for (int i = 0; i < numLines; i++) {
    display.drawString(lines[i], 60, y, 2);
    y += 48;
  }
  Serial.printf("update start, BUSY=%d\n", digitalRead(4));
  uint32_t t0 = millis();
  display.update();
  // A real Spectra 6 full refresh holds BUSY low ~27 s. If this returns in
  // ~1 s with BUSY stuck HIGH, the panel never executed the refresh.
  uint32_t dt = millis() - t0;
  Serial.printf("update done in %lums, BUSY=%d\n", dt, digitalRead(4));
  if (dt < 5000 && digitalRead(4)) {
    Serial.println("WARN: refresh returned fast with BUSY high; "
                   "panel may not have executed it");
  }
  Serial.println("drawStatus: done");
  return true;
}

void Gdeb0709e01Panel::sleep() { display.panel().sleep(); }
