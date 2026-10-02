#include "QuietHours.h"

namespace spectra {

bool inQuietWindow(int nowMin, int startMin, int endMin) {
  if (startMin == endMin) return false;
  if (startMin < endMin) return nowMin >= startMin && nowMin < endMin;
  return nowMin >= startMin || nowMin < endMin;  // wraps midnight
}

uint32_t secondsToWindowEnd(int nowMin, int endMin) {
  int deltaMin = endMin - nowMin;
  if (deltaMin <= 0) deltaMin += 24 * 60;
  return (uint32_t)deltaMin * 60u;
}

}  // namespace spectra
