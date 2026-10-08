#include "EinkLayout.h"

#include <TFT_eSPI.h>
#include <math.h>
#include <string.h>

#include <qrcode.h>

#include "../hal/Panel.h"
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

void EinkLayout::statusBackdrop() {
  drawBackdrop(-420, 410, 1275, 1425);
}

void EinkLayout::setupBackdrop() {
  drawBackdrop(-280, 190, 1245, 1075);
}

void EinkLayout::drawBackdrop(int clayX, int clayY, int sageCenterX,
                              int sageCenterY) {
  // Solid 6-ink backdrop. The mockups use frosted-glass translucency, but
  // the Spectra 6 panel has only 6 opaque inks — no alpha blending exists.
  // Earlier halftone-band dithering tried to fake translucency and produced
  // visible striping on hardware that matched neither the mockup nor a clean
  // solid look. Solid shapes are the honest rendering.
  constexpr int clayW = 920;
  constexpr int clayH = 560;
  constexpr int sageRadius = 425;
  s_->fillRoundRect(clayX, clayY, clayW, clayH, 170, INK_RED);
  s_->fillCircle(sageCenterX, sageCenterY, sageRadius, INK_GREEN);
}

void EinkLayout::wordmark() {
  textCenter(600, 166, "F O L I O F R A M E", theme::FONT_SMALL, 2,
             INK_RED);
}

void EinkLayout::statusIcon(PanelStatusIcon icon) {
  const int cx = 600;
  const int cy = 485;
  s_->fillCircle(cx, cy, 105, INK_WHITE);
  s_->drawCircle(cx, cy, 105, theme::INK_BLACK);
  s_->drawCircle(cx, cy, 103, theme::INK_BLACK);

  const uint16_t accent =
      (icon == PanelStatusIcon::Success) ? INK_GREEN : INK_RED;
  switch (icon) {
    case PanelStatusIcon::Checking:
      s_->drawCircle(cx, cy, 50, accent);
      s_->fillRect(cx + 28, cy - 54, 35, 28, INK_WHITE);
      s_->drawLine(cx + 41, cy - 46, cx + 62, cy - 46, accent);
      s_->drawLine(cx + 62, cy - 46, cx + 62, cy - 25, accent);
      s_->drawLine(cx, cy, cx, cy - 31, INK_BLACK);
      s_->drawLine(cx, cy, cx + 25, cy + 13, INK_BLACK);
      break;
    case PanelStatusIcon::Download:
      s_->drawRoundRect(cx - 46, cy - 40, 92, 75, 8, accent);
      s_->drawLine(cx, cy - 62, cx, cy + 16, accent);
      s_->drawLine(cx - 29, cy - 12, cx, cy + 17, accent);
      s_->drawLine(cx + 29, cy - 12, cx, cy + 17, accent);
      s_->drawLine(cx - 54, cy + 58, cx + 54, cy + 58, accent);
      break;
    case PanelStatusIcon::Verifying:
      s_->drawLine(cx, cy - 68, cx + 49, cy - 48, accent);
      s_->drawLine(cx + 49, cy - 48, cx + 43, cy + 16, accent);
      s_->drawLine(cx + 43, cy + 16, cx, cy + 64, accent);
      s_->drawLine(cx, cy + 64, cx - 43, cy + 16, accent);
      s_->drawLine(cx - 43, cy + 16, cx - 49, cy - 48, accent);
      s_->drawLine(cx - 49, cy - 48, cx, cy - 68, accent);
      s_->drawLine(cx - 24, cy, cx - 5, cy + 20, accent);
      s_->drawLine(cx - 5, cy + 20, cx + 31, cy - 22, accent);
      break;
    case PanelStatusIcon::Success:
      s_->drawCircle(cx, cy, 57, accent);
      s_->drawLine(cx - 31, cy, cx - 8, cy + 24, accent);
      s_->drawLine(cx - 8, cy + 24, cx + 37, cy - 27, accent);
      break;
    case PanelStatusIcon::Failure:
      s_->drawCircle(cx, cy, 57, accent);
      s_->drawLine(cx - 25, cy - 25, cx + 25, cy + 25, accent);
      s_->drawLine(cx + 25, cy - 25, cx - 25, cy + 25, accent);
      break;
    case PanelStatusIcon::Battery:
      s_->drawRoundRect(cx - 58, cy - 34, 110, 68, 8, accent);
      s_->fillRect(cx + 52, cy - 15, 12, 30, accent);
      s_->fillRect(cx - 46, cy - 22, 63, 44, accent);
      break;
    case PanelStatusIcon::CriticalBattery:
      s_->drawTriangle(cx, cy - 65, cx - 69, cy + 54, cx + 69, cy + 54,
                       accent);
      s_->drawLine(cx, cy - 24, cx, cy + 15, accent);
      s_->fillCircle(cx, cy + 35, 4, accent);
      break;
    case PanelStatusIcon::WifiLost:
      wifiIcon(cx, cy + 18, 112, accent);
      s_->drawLine(cx - 58, cy - 58, cx + 58, cy + 58, INK_BLACK);
      s_->drawLine(cx + 58, cy - 58, cx - 58, cy + 58, INK_BLACK);
      break;
    case PanelStatusIcon::WifiWeak:
      wifiIcon(cx, cy + 18, 112, accent);
      break;
    case PanelStatusIcon::PhotoError:
      s_->drawRoundRect(cx - 61, cy - 48, 122, 96, 8, accent);
      s_->fillCircle(cx + 28, cy - 22, 9, accent);
      s_->drawLine(cx - 43, cy + 30, cx - 9, cy - 4, accent);
      s_->drawLine(cx - 9, cy - 4, cx + 10, cy + 15, accent);
      s_->drawLine(cx + 10, cy + 15, cx + 30, cy - 3, accent);
      s_->drawLine(cx + 30, cy - 3, cx + 44, cy + 11, accent);
      break;
  }
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

void EinkLayout::wrapCenter(int cx, int y, int maxChars, int lineHeight,
                            const char* str, uint8_t font, uint8_t textSize,
                            uint16_t color) {
  if (!str || maxChars <= 0) return;
  if (maxChars > 90) maxChars = 90;
  char line[96];
  int used = 0;
  const char* p = str;

  while (*p) {
    while (*p == ' ') ++p;
    if (!*p) break;
    const char* word = p;
    while (*p && *p != ' ') ++p;
    int wordLen = static_cast<int>(p - word);

    if (used && used + 1 + wordLen > maxChars) {
      line[used] = '\0';
      textCenter(cx, y, line, font, textSize, color);
      y += lineHeight;
      used = 0;
    }
    if (used) line[used++] = ' ';

    while (wordLen > 0) {
      int copy = wordLen;
      if (copy > maxChars - used) copy = maxChars - used;
      if (copy <= 0) {
        line[used] = '\0';
        textCenter(cx, y, line, font, textSize, color);
        y += lineHeight;
        used = 0;
        continue;
      }
      memcpy(line + used, word, static_cast<size_t>(copy));
      used += copy;
      word += copy;
      wordLen -= copy;
      if (wordLen > 0) {
        line[used] = '\0';
        textCenter(cx, y, line, font, textSize, color);
        y += lineHeight;
        used = 0;
      }
    }
  }
  if (used) {
    line[used] = '\0';
    textCenter(cx, y, line, font, textSize, color);
  }
}

void EinkLayout::progressBar(uint8_t percent) {
  if (percent > 100) percent = 100;
  constexpr int x = 240;
  constexpr int labelY = 1010;
  constexpr int y = 1067;
  constexpr int width = 720;
  constexpr int height = 30;
  textLeft(x, labelY, "Downloading", theme::FONT_SMALL, 2, INK_BLACK);
  char label[8];
  snprintf(label, sizeof(label), "%u%%", percent);
  text(x + width, labelY, label, theme::FONT_SMALL, 2, INK_BLACK, 2);
  s_->drawRoundRect(x, y, width, height, 15, INK_RED);
  const int innerWidth = (width - 8) * percent / 100;
  if (innerWidth > 0) s_->fillRect(x + 4, y + 4, innerWidth, height - 8, INK_RED);
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
  for (int y = 334; y < 450; y += 8) {
    s_->fillRect(100, y, 1000, 2, INK_WHITE);
  }
  s_->drawRoundRect(82, 326, 1036, 132, 18, INK_WHITE);
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

void EinkLayout::helpQR(int targetSize, int right, int bottom) {
  static const char* kHelpUrl = "https://github.com/CJ8664/folioframe";
  const int captionSpace = targetSize <= 200 ? 34 : 40;
  const int modules = 41;
  const int qrSize = modules * (targetSize / modules);
  const int x = theme::DISPLAY_W - right - targetSize;
  const int y = theme::DISPLAY_H - bottom - targetSize - captionSpace;
  qr(kHelpUrl, x + (targetSize - qrSize) / 2, y, targetSize, INK_BLACK);
  textCenter(x + targetSize / 2, y + qrSize + (targetSize <= 200 ? 16 : 8),
             "Scan for help", theme::FONT_SMALL, targetSize <= 200 ? 1 : 2,
             INK_BLACK);
}

}  // namespace folioframe
