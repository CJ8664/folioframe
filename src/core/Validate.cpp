#include "Validate.h"

namespace spectra {

bool validDeviceName(const std::string& name) {
  if (name.size() < 1 || name.size() > 24) return false;
  if (name.front() == '-' || name.back() == '-') return false;
  for (char c : name) {
    bool ok = (c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-';
    if (!ok) return false;
  }
  return true;
}

bool validIntervalMinutes(uint32_t minutes) {
  switch (minutes) {
    case 15:
    case 30:
    case 60:
    case 120:
    case 240:
    case 480:
    case 720:
    case 1440:
      return true;
    default:
      return false;
  }
}

bool validTimezone(const std::string& tz) {
  if (tz == "auto") return true;
  // POSIX TZ: e.g. "PST8PDT,M3.2.0,M11.1.0". Basic sanity only.
  if (tz.empty() || tz.size() > 64) return false;
  for (char c : tz) {
    bool ok = (c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
              (c >= '0' && c <= '9') || c == '+' || c == '-' || c == ',' ||
              c == '.' || c == ':';
    if (!ok) return false;
  }
  return true;
}

}  // namespace spectra
