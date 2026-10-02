#pragma once
// Field validators shared by the portal and the firmware. Pure logic.
#include <cstdint>
#include <string>

namespace spectra {

// 1-24 chars: lowercase alnum + hyphen, not leading/trailing hyphen.
bool validDeviceName(const std::string& name);

// Refresh interval in minutes: one of the offered choices.
bool validIntervalMinutes(uint32_t minutes);

// Timezone: "auto" or a POSIX TZ string (basic sanity).
bool validTimezone(const std::string& tz);

}  // namespace spectra
