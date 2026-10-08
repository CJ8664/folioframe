#include "EinkLayout.h"

#include <TFT_eSPI.h>

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
  // 58px diameter circle, 3px black ring, number centered (26px black).
  s_->drawCircle(cx, y, 29, INK_BLACK);
  s_->drawCircle(cx, y, 28, INK_BLACK);
  s_->drawCircle(cx, y, 27, INK_BLACK);
  char buf[4];
  snprintf(buf, sizeof(buf), "%d", n);
  textCenter(cx, y, buf, theme::FONT_BODY, 1, INK_BLACK);
}

void EinkLayout::networkCard(const char* apName) {
  // Red rounded card (82,326,1036,132,r18) with white AP name centered.
  s_->fillRoundRect(82, 326, 1036, 132, 18, INK_RED);
  textCenter(82 + 1036 / 2, 326 + 66, apName, theme::FONT_BODY, 1, INK_WHITE);
}

void EinkLayout::qr(const char* text, int x, int y, int targetSize) {
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
        s_->fillRect(x + col * scale, y + row * scale, scale, scale, INK_BLACK);
      }
    }
  }
}

void EinkLayout::qrCard(int x, int y, int w, const char* label,
                        const char* heading, const char* qrText,
                        const char* url) {
  // Card: white with 2px black border, 470px tall.
  const int h = 470;
  s_->fillRect(x, y, w, h, INK_WHITE);
  s_->drawRect(x, y, w, h, INK_BLACK);
  s_->drawRect(x + 1, y + 1, w - 2, h - 2, INK_BLACK);

  int cy = y + 24;
  // Label: 16px green uppercase, centered.
  textCenter(x + w / 2, cy, label, theme::FONT_SMALL, 1, INK_GREEN);
  cy += 36;
  // Heading: 27px black, centered.
  textCenter(x + w / 2, cy, heading, theme::FONT_BODY, 1, INK_BLACK);
  cy += 48;

  // QR: 248px, centered horizontally.
  const int qrSize = 248;
  const int qrX = x + (w - qrSize) / 2;
  qr(qrText, qrX, cy, qrSize);
  cy += qrSize + 20;

  // URL: 16px red, centered.
  textCenter(x + w / 2, cy, url, theme::FONT_SMALL, 1, INK_RED);
}

void EinkLayout::helpQR() {
  static const char* kHelpUrl = "https://github.com/CJ8664/folioframe";
  const int kSize = 296;
  const int x = 1200 - 76 - kSize;
  const int y = 1600 - 64 - kSize - 40;
  qr(kHelpUrl, x, y, kSize);
  textCenter(x + kSize / 2, y + kSize + 8, "Scan for help", theme::FONT_SMALL,
             1, INK_BLACK);
}

}  // namespace folioframe
