#pragma once
// NTP + timezone. "auto" tries IP geolocation once, else UTC.
#include <Arduino.h>

class TimeSync {
 public:
  // Returns true when the clock is sane (post-2020).
  bool begin(const char* timezoneSetting);
  int32_t utcOffsetMinutes() const { return offsetMin_; }

 private:
  int32_t offsetMin_ = 0;
  bool fetchIpApiOffset();
};
