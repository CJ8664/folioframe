#pragma once
// Persistent settings (NVS via Preferences). Validation delegates to core/.
#include <Arduino.h>

#include "../core/Validate.h"

struct Settings {
  char imageUrl[513];
  uint32_t intervalMinutes;  // 15,30,60,120,240,480,720,1440
  bool quietEnabled;
  int quietStartMin;  // local minutes since midnight
  int quietEndMin;
  char timezone[65];  // "auto" or POSIX TZ string
  char deviceName[25];
  uint8_t orientation;  // 0..3
  char etag[64];        // cached frame ETag for If-None-Match
  char otaBase[129];    // e.g. http://192.168.1.10:8765 ; empty = OTA off
};

class Config {
 public:
  void load();  // NVS → settings_; defaults when missing
  void save();
  void resetDefaults();
  Settings& get() { return settings_; }

  // Field-level validation (portal use). Returns false + sets err.
  static bool validate(const Settings& s, String& err);

 private:
  Settings settings_;
  void setDefaults();
};
