#include "BatteryCurve.h"

namespace spectra {

// (millivolts, percent) — typical 1S LiPo discharge curve.
static const uint16_t kMv[] = {3400, 3500, 3600, 3650, 3700,
                               3750, 3800, 3850, 3900, 4000,
                               4100, 4200};
static const uint8_t kPct[] = {0, 3, 8, 15, 25,
                               35, 45, 55, 65, 78,
                               90, 100};
static const int kPoints = sizeof(kMv) / sizeof(kMv[0]);

uint8_t batteryPercent(uint16_t mv) {
  if (mv <= kMv[0]) return 0;
  for (int i = 1; i < kPoints; i++) {
    if (mv <= kMv[i]) {
      // Linear interpolation between kMv[i-1] and kMv[i].
      uint16_t span = kMv[i] - kMv[i - 1];
      uint8_t pspan = kPct[i] - kPct[i - 1];
      return kPct[i - 1] + (uint8_t)(((uint32_t)(mv - kMv[i - 1]) * pspan) / span);
    }
  }
  return 100;
}

}  // namespace spectra
