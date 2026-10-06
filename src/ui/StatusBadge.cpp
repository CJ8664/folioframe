#include "StatusBadge.h"

#include <stdio.h>

namespace spectra {
namespace {

// Spectra 6 hardware nibbles (see hal/Panel.h).
constexpr uint8_t N_WHITE = 0x0;
constexpr uint8_t N_BLACK = 0xF;
constexpr uint8_t N_RED = 0x6;

// Badge geometry: small bottom-right chip.
constexpr int kBadgeW = 232;
constexpr int kBadgeH = 72;
constexpr int kMargin = 28;
constexpr int kPad = 12;
constexpr int kBorder = 3;

inline void setPx(uint8_t* buf, int w, int h, int x, int y, uint8_t nib) {
  if (x < 0 || y < 0 || x >= w || y >= h) return;
  size_t i = ((size_t)(unsigned)y * (unsigned)w + (unsigned)x) / 2;
  if (x & 1)
    buf[i] = (uint8_t)((buf[i] & 0xF0) | (nib & 0x0F));
  else
    buf[i] = (uint8_t)((buf[i] & 0x0F) | ((nib & 0x0F) << 4));
}

void fillRect(uint8_t* buf, int w, int h, int x0, int y0, int rw, int rh,
              uint8_t nib) {
  for (int y = y0; y < y0 + rh; y++)
    for (int x = x0; x < x0 + rw; x++) setPx(buf, w, h, x, y, nib);
}

void fillCircle(uint8_t* buf, int w, int h, int cx, int cy, int r,
                uint8_t nib) {
  for (int y = cy - r; y <= cy + r; y++)
    for (int x = cx - r; x <= cx + r; x++) {
      int dx = x - cx, dy = y - cy;
      if (dx * dx + dy * dy <= r * r) setPx(buf, w, h, x, y, nib);
    }
}

// 5x7 column-major font, LSB = top pixel. Only what the badge needs.
constexpr uint8_t kFont[][5] = {
    {0x3E, 0x51, 0x49, 0x45, 0x3E},  // 0
    {0x00, 0x42, 0x7F, 0x40, 0x00},  // 1
    {0x42, 0x61, 0x51, 0x49, 0x46},  // 2
    {0x21, 0x41, 0x45, 0x4B, 0x31},  // 3
    {0x18, 0x14, 0x12, 0x7F, 0x10},  // 4
    {0x27, 0x45, 0x45, 0x45, 0x39},  // 5
    {0x3C, 0x4A, 0x49, 0x49, 0x30},  // 6
    {0x01, 0x71, 0x09, 0x05, 0x03},  // 7
    {0x36, 0x49, 0x49, 0x49, 0x36},  // 8
    {0x06, 0x49, 0x49, 0x29, 0x1E},  // 9
    {0x62, 0x64, 0x08, 0x16, 0x26},  // %
    {0x08, 0x08, 0x08, 0x08, 0x08},  // -
};

int fontIndex(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c == '%') return 10;
  if (c == '-') return 11;
  return -1;
}

void drawText(uint8_t* buf, int w, int h, int x, int y, const char* s,
              int scale, uint8_t nib) {
  for (const char* p = s; *p; p++) {
    int fi = fontIndex(*p);
    if (fi >= 0) {
      for (int col = 0; col < 5; col++) {
        uint8_t bits = kFont[fi][col];
        for (int row = 0; row < 7; row++) {
          if (bits & (1u << row))
            fillRect(buf, w, h, x + col * scale, y + row * scale, scale,
                     scale, nib);
        }
      }
    }
    x += 6 * scale;
  }
}

}  // namespace

void drawStatusBadge(uint8_t* buf, size_t len, uint16_t width, uint16_t height,
                     int rssiDbm, uint8_t batteryPct, bool updatePending) {
  if (!buf) return;
  const int w = width, h = height;
  if (len < (size_t)w * h / 2) return;  // not a full frame; don't touch it
  if (w < kBadgeW + 2 * kMargin || h < kBadgeH + 2 * kMargin) return;

  const int bx = w - kMargin - kBadgeW;
  const int by = h - kMargin - kBadgeH;
  const int cy = by + kBadgeH / 2;

  // Chip: white wash fill, dark ink border.
  fillRect(buf, w, h, bx, by, kBadgeW, kBadgeH, N_WHITE);
  fillRect(buf, w, h, bx, by, kBadgeW, kBorder, N_BLACK);
  fillRect(buf, w, h, bx, by + kBadgeH - kBorder, kBadgeW, kBorder, N_BLACK);
  fillRect(buf, w, h, bx, by, kBorder, kBadgeH, N_BLACK);
  fillRect(buf, w, h, bx + kBadgeW - kBorder, by, kBorder, kBadgeH, N_BLACK);

  // Wi-Fi bars: 4 ascending bars, filled per RSSI.
  int bars = 1;
  if (rssiDbm >= -55)
    bars = 4;
  else if (rssiDbm >= -65)
    bars = 3;
  else if (rssiDbm >= -75)
    bars = 2;
  const int barW = 8, barGap = 5;
  const int barH[4] = {14, 22, 30, 38};
  const int wx = bx + kPad;
  const int wBase = by + kBadgeH - kPad;
  for (int i = 0; i < 4; i++) {
    const int x0 = wx + i * (barW + barGap);
    const int y0 = wBase - barH[i];
    if (i < bars) {
      fillRect(buf, w, h, x0, y0, barW, barH[i], N_BLACK);
    } else {
      // Hollow outline for bars above the current signal.
      fillRect(buf, w, h, x0, y0, barW, 2, N_BLACK);
      fillRect(buf, w, h, x0, y0 + barH[i] - 2, barW, 2, N_BLACK);
      fillRect(buf, w, h, x0, y0, 2, barH[i], N_BLACK);
      fillRect(buf, w, h, x0 + barW - 2, y0, 2, barH[i], N_BLACK);
    }
  }

  // Battery: outline + nub, fill proportional to charge.
  const int batX = wx + 4 * barW + 3 * barGap + 14;
  const int batW = 44, batH = 24;
  const int batY = cy - batH / 2;
  fillRect(buf, w, h, batX, batY, batW, 2, N_BLACK);
  fillRect(buf, w, h, batX, batY + batH - 2, batW, 2, N_BLACK);
  fillRect(buf, w, h, batX, batY, 2, batH, N_BLACK);
  fillRect(buf, w, h, batX + batW - 2, batY, 2, batH, N_BLACK);
  fillRect(buf, w, h, batX + batW, cy - 5, 5, 10, N_BLACK);  // nub
  if (batteryPct > 0) {
    const int fillW = (batW - 8) * (batteryPct > 100 ? 100 : batteryPct) / 100;
    fillRect(buf, w, h, batX + 4, batY + 4, fillW, batH - 8, N_BLACK);
  }

  // Battery percent text (5x7 @ 2x).
  char battStr[6];
  if (batteryPct == 0)
    snprintf(battStr, sizeof(battStr), "--");
  else
    snprintf(battStr, sizeof(battStr), "%u%%",
             batteryPct > 100 ? 100 : batteryPct);
  const int tx = batX + batW + 5 + 12;
  drawText(buf, w, h, tx, cy - 7, battStr, 2, N_BLACK);

  // Update dot: red, only when a manual update is staged.
  if (updatePending)
    fillCircle(buf, w, h, bx + kBadgeW - kPad - 8, cy, 8, N_RED);
}

}  // namespace spectra
