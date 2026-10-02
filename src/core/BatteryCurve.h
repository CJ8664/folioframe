#pragma once
// 1S LiPo discharge curve → percent. Piecewise-linear interpolation,
// clamped to [0, 100]. Pure logic.
#include <cstdint>

namespace spectra {

uint8_t batteryPercent(uint16_t millivolts);

}  // namespace spectra
