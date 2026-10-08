#include "EinkLayout.h"

#include <TFT_eSPI.h>
#include <math.h>

#include <qrcode.h>

#include "EinkTheme.h"

namespace folioframe {
namespace {

using theme::INK_BLACK;
using theme::INK_GREEN;
using theme::INK_RED;
using theme::INK_WHITE;

// TFT_eSPI datum constants (for readability)
constexpr uint8_t kTL = 0;  // TL_DATUM
constexpr uint8_t kMC = 4;  // MC_DATUM

}  // namespace

void EinkLayout::clear() {
  s_->fillRect(0, 0, theme::DISPLAY_W, theme::DISPLAY_H, INK_WHITE);
}

void EinkLayout::text(int x, int y, const char* str, uint8_t font,
                      uint8_t textSize, uint16_t color, uint8_t datum) {
  s_->setTextColor(color);
  s_->setTextDatum(datum);
  s_->setTextSize(textSize);
  s_->drawString(str, x, y, font);
  s_->setTextSize(1);
  s_->setTextDatum(kTL);
}

void EinkLayout::header() {
  // "FolioFrame Setup", 78px (font4 x3), left-aligned at (80,130).
  textLeft(80, 130, "FolioFrame Setup", theme::FONT_TITLE, 3, INK_BLACK);
}

void EinkLayout::topline(const char* spacedText) {
  // 16px sage uppercase at (82,67). Caller pre-spaces for letter-spacing.
  textLeft(82, 67, spacedText, theme::FONT_SMALL, 1, INK_GREEN);
}

void EinkLayout::rule(int y) {
  s_->fillRect(82, y, 1036, 2, INK_BLACK);
}

void EinkLayout::stepCircle(int cx, int y, int n) {
  // Mockup: light circle with clay-colored number, thin border.
  // 58px diameter.
  s_->fillCircle(cx, y, 29, INK_WHITE);
  s_->drawCircle(cx, y, 29, INK_RED);
  s_->drawCircle(cx, y, 28, INK_RED);
  char buf[4];
  snprintf(buf, sizeof(buf), "%d", n);
  textCenter(cx, y, buf, theme::FONT_BODY, 1, INK_RED);
}

void EinkLayout::networkCard(const char* apName) {
  // Clay rounded card (82,326,1036,132,r18) with white Wi-Fi icon + AP name.
  // Mockup: icon at left, AP name centered in remaining space.
  s_->fillRoundRect(82, 326, 1036, 132, 18, INK_RED);
  wifiIcon(170, 392, 56, INK_WHITE);
  // AP name: white, centered between icon and right edge
  textCenter(640, 326 + 53, apName, theme::FONT_BODY, 1, INK_WHITE);
}

void EinkLayout::qr(const char* text, int x, int y, int targetSize,
                    uint16_t qrColor) {
  QRCode qrcode;
  uint8_t qrcodeData[qrcode_getBufferSize(6)];
  // Version 6 at ECC 0 holds ~106 bytes. If the text doesn't fit,
  // draw the URL as text instead of a garbage QR.
  if (qrcode_initText(&qrcode, qrcodeData, 6, 0, text) != 0) {
    textCenter(x + targetSize / 2, y + targetSize / 2, text, theme::FONT_SMALL,
               1, INK_RED);
    return;
  }

  int scale = targetSize / qrcode.size;
  if (scale < 1) scale = 1;
  int qrSize = qrcode.size * scale;

  s_->fillRect(x, y, qrSize, qrSize, INK_WHITE);
  for (uint8_t row = 0; row < qrcode.size; row++) {
    for (uint8_t col = 0; col < qrcode.size; col++) {
      if (qrcode_getModule(&qrcode, col, row)) {
        s_->fillRect(x + col * scale, y + row * scale, scale, scale, qrColor);
      }
    }
  }
}

void EinkLayout::frameIcon(int x, int y, int size, uint16_t color) {
  // Picture frame: outer rect with thick ornate-ish border.
  // Mockup has a decorative frame; we approximate with double border
  // plus corner accents.
  int t = size / 10;
  if (t < 4) t = 4;
  // Outer frame
  for (int i = 0; i < t; i++) {
    s_->drawRect(x + i, y + i, size - 2 * i, size - 2 * i, color);
  }
  // Inner "photo" area
  int inset = size / 3;
  s_->drawRect(x + inset, y + inset, size - 2 * inset, size - 2 * inset, color);
  // Corner accents (small squares at corners for ornate feel)
  int c = size / 8;
  s_->fillRect(x, y, c, c, color);
  s_->fillRect(x + size - c, y, c, c, color);
  s_->fillRect(x, y + size - c, c, c, color);
  s_->fillRect(x + size - c, y + size - c, c, c, color);
}

void EinkLayout::wifiIcon(int cx, int cy, int size, uint16_t color) {
  // Wi-Fi: dot + three arcs above. Size = overall width.
  int r = size / 2;
  // Dot at bottom center
  s_->fillCircle(cx, cy, r / 5, color);
  // Three arcs (draw as circle outlines, only top portion visible via clip)
  // Simplified: three concentric circle outlines centered below the dot
  for (int i = 1; i <= 3; i++) {
    int ar = (r * i) / 3;
    // Draw arc from 200° to 340° (top portion)
    for (int a = 200; a <= 340; a += 3) {
      float rad = a * 3.14159f / 180.0f;
      int px = cx + (int)(ar * cos(rad));
      int py = cy + (int)(ar * sin(rad)) - r / 4;
      s_->fillCircle(px, py, 2, color);
    }
  }
}

void EinkLayout::qrCard(int x, int y, int w, const char* label,
                        const char* heading, const char* qrText,
                        const char* url, uint16_t qrColor) {
  // Card: white with subtle 1px border (mockup has soft shadow which
  // e-paper can't do; thin border is the closest).
  const int h = 470;
  s_->fillRect(x, y, w, h, INK_WHITE);
  s_->drawRoundRect(x, y, w, h, 12, INK_BLACK);

  int cy = y + 24;
  // Heading: 26px black bold, centered. (Mockup: heading on top)
  textCenter(x + w / 2, cy, heading, theme::FONT_BODY, 1, INK_BLACK);
  cy += 38;
  // Label: 16px green uppercase, centered. (Mockup: label below heading)
  textCenter(x + w / 2, cy, label, theme::FONT_SMALL, 1, INK_GREEN);
  cy += 34;

  // QR: 248px, centered horizontally, in qrColor.
  const int qrSize = 248;
  const int qrX = x + (w - qrSize) / 2;
  qr(qrText, qrX, cy, qrSize, qrColor);
  cy += qrSize + 20;

  // URL: 16px red, centered.
  textCenter(x + w / 2, cy, url, theme::FONT_SMALL, 1, INK_RED);
}

void EinkLayout::helpQR() {
  static const char* kHelpUrl = "https://github.com/CJ8664/folioframe";
  const int kSize = 296;
  const int x = 1200 - 76 - kSize;
  const int y = 1600 - 64 - kSize - 40;
  qr(kHelpUrl, x, y, kSize, INK_BLACK);
  textCenter(x + kSize / 2, y + kSize + 8, "Scan for help", theme::FONT_SMALL,
             1, INK_BLACK);
}

}  // namespace folioframe
