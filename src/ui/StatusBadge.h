#pragma once
// Tiny corner status badge composited into the packed-4bpp frame buffer
// just before the panel paint: Wi-Fi signal bars, battery percent, and
// (only when a manual update is staged) an update dot.
//
// Deliberately NOT a status bar: a small bottom-right chip in muted
// colors (white wash, dark ink icons on the 6-color Spectra panel) so the
// photo stays the hero. Text status screens don't get the badge -- they
// already convey state.
#include <stddef.h>
#include <stdint.h>

namespace spectra {

// Composite the badge into buf (packed 4bpp: 2 px/byte, high nibble first,
// width*height pixels, rows top->bottom). Silently skips when the buffer
// is too small for the badge.
//   rssiDbm: Wi-Fi RSSI in dBm (e.g. -60).
//   batteryPct: 0..100; 0 = unknown (shows "--").
//   updatePending: draw the red update dot.
void drawStatusBadge(uint8_t* buf, size_t len, uint16_t width, uint16_t height,
                     int rssiDbm, uint8_t batteryPct, bool updatePending);

}  // namespace spectra
