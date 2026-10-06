#pragma once
// Persistent settings (NVS via Preferences). Validation delegates to core/.
//
// Two namespaces:
//   "spectra"     display settings (server URL, interval, quiet hours...)
//   "spectra_dev" the device Bearer token from pairing -- kept apart so a
//                 settings export/debug dump never carries the credential.
#include <Arduino.h>

#include "../core/Validate.h"

struct Settings {
  char serverUrl[257];  // e.g. "https://frame.example.com"; empty = unset
  uint32_t intervalMinutes;  // 15,30,60,120,240,480,720,1440
  bool quietEnabled;
  int quietStartMin;  // local minutes since midnight
  int quietEndMin;
  char timezone[65];  // "auto" or POSIX TZ string
  char deviceName[25];
  uint8_t orientation;  // 0..3
  char etag[64];        // cached frame ETag for If-None-Match
  char otaBase[129];  // manual OTA base override; empty = use serverUrl
  bool otaAutoInstall;      // true = check+install silently on wake (default)
  bool otaUpdatePending;    // manual mode: update found, not yet installed
  uint32_t otaPendingBuild;     // build number of the pending update
  char otaPendingVersion[25];   // version string of pending update ("" if none)
};

class Config {
 public:
  void load();  // NVS → settings_; defaults when missing
  void save();
  void resetDefaults();
  Settings& get() { return settings_; }

  // Stage (or clear) a manual-mode pending update with read-compare-write:
  // skips the NVS write entirely when the stored values already match, so
  // re-staging the same pending update on every wake doesn't cost flash
  // wear. The in-memory copy is updated either way. Behavior (stored
  // values, field truncation) is identical to save() for these fields.
  void savePendingUpdate(bool pending, uint32_t build, const char* version);

  // Device pairing credential (separate NVS namespace, never logged).
  String deviceToken();
  void setDeviceToken(const String& token);
  void clearDeviceToken();

  // Field-level validation (portal use). Returns false + sets err.
  static bool validate(const Settings& s, String& err);

 private:
  Settings settings_;
  void setDefaults();
};
