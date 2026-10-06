#include "Config.h"

#include <Preferences.h>

#include "../core/UrlTemplate.h"

static const char* kNs = "spectra";
static const char* kDevNs = "spectra_dev";
// NOTE: these NVS namespace names are intentionally NOT renamed to FolioFrame.
// Renaming them would orphan the stored Wi-Fi credentials, server URL, and
// device pairing token on already-deployed devices, forcing a re-pair.
// They are internal identifiers, never shown to the user.

void Config::setDefaults() {
  memset(&settings_, 0, sizeof(settings_));
  settings_.serverUrl[0] = '\0';  // must be set via portal before pairing
  settings_.intervalMinutes = 60;
  settings_.quietEnabled = true;
  settings_.quietStartMin = 22 * 60;  // 22:00
  settings_.quietEndMin = 7 * 60;     // 07:00
  strncpy(settings_.timezone, "auto", sizeof(settings_.timezone) - 1);
  strncpy(settings_.deviceName, "folioframe",
          sizeof(settings_.deviceName) - 1);
  settings_.orientation = 0;
  settings_.otaAutoInstall = true;  // silent auto-install is the default
  settings_.otaUpdatePending = false;
  settings_.otaPendingBuild = 0;
  settings_.otaPendingVersion[0] = '\0';
}

void Config::resetDefaults() {
  setDefaults();
  save();
}

void Config::load() {
  Preferences p;
  if (!p.begin(kNs, true)) {
    setDefaults();
    return;
  }
  setDefaults();  // base, then override with stored keys
  p.getString("srv", settings_.serverUrl, sizeof(settings_.serverUrl));
  settings_.intervalMinutes = p.getUInt("interval", settings_.intervalMinutes);
  settings_.quietEnabled = p.getBool("qen", settings_.quietEnabled);
  settings_.quietStartMin = p.getInt("qs", settings_.quietStartMin);
  settings_.quietEndMin = p.getInt("qe", settings_.quietEndMin);
  p.getString("tz", settings_.timezone, sizeof(settings_.timezone));
  p.getString("name", settings_.deviceName, sizeof(settings_.deviceName));
  settings_.orientation = p.getUChar("orient", settings_.orientation);
  p.getString("etag", settings_.etag, sizeof(settings_.etag));
  p.getString("otabase", settings_.otaBase, sizeof(settings_.otaBase));
  settings_.otaAutoInstall = p.getBool("otaauto", settings_.otaAutoInstall);
  settings_.otaUpdatePending =
      p.getBool("otapend", settings_.otaUpdatePending);
  settings_.otaPendingBuild =
      p.getUInt("otapbld", settings_.otaPendingBuild);
  p.getString("otapver", settings_.otaPendingVersion,
              sizeof(settings_.otaPendingVersion));
  p.end();

  // Migration from the v1 URL-template firmware: the old "url" key held an
  // image URL template (containing {tokens}). A server URL never does, so
  // a template here means "never configured for v2" -- start unset.
  if (strchr(settings_.serverUrl, '{') || strchr(settings_.serverUrl, '}')) {
    settings_.serverUrl[0] = '\0';
    save();
  }

  String err;
  if (!validate(settings_, err)) setDefaults();  // corrupt → safe defaults
}

void Config::save() {
  Preferences p;
  if (!p.begin(kNs, false)) return;
  p.putString("srv", settings_.serverUrl);
  p.putUInt("interval", settings_.intervalMinutes);
  p.putBool("qen", settings_.quietEnabled);
  p.putInt("qs", settings_.quietStartMin);
  p.putInt("qe", settings_.quietEndMin);
  p.putString("tz", settings_.timezone);
  p.putString("name", settings_.deviceName);
  p.putUChar("orient", settings_.orientation);
  p.putString("etag", settings_.etag);
  p.putString("otabase", settings_.otaBase);
  p.putBool("otaauto", settings_.otaAutoInstall);
  p.putBool("otapend", settings_.otaUpdatePending);
  p.putUInt("otapbld", settings_.otaPendingBuild);
  p.putString("otapver", settings_.otaPendingVersion);
  p.end();
}

String Config::deviceToken() {
  Preferences p;
  String t;
  if (p.begin(kDevNs, true)) {
    t = p.getString("dtoken", "");
    p.end();
  }
  return t;
}

void Config::setDeviceToken(const String& token) {
  Preferences p;
  if (!p.begin(kDevNs, false)) return;
  p.putString("dtoken", token);
  p.end();
}

void Config::clearDeviceToken() {
  Preferences p;
  if (!p.begin(kDevNs, false)) return;
  p.remove("dtoken");
  p.end();
}

bool Config::validate(const Settings& s, String& err) {
  using namespace spectra;
  // Empty server URL is allowed (means "not configured yet"); the portal
  // forces it before pairing. When set, it must be an http(s) URL that
  // fits the 256-char NVS field (validImageUrl allows 512, too long here).
  if (s.serverUrl[0]) {
    if (strlen(s.serverUrl) > 256 ||
        !validImageUrl(std::string(s.serverUrl))) {
      err = "server URL must be http(s):// and <= 256 chars";
      return false;
    }
  }
  if (!validIntervalMinutes(s.intervalMinutes)) {
    err = "interval must be one of 15/30/60/120/240/480/720/1440";
    return false;
  }
  if (s.quietEnabled) {
    if (s.quietStartMin < 0 || s.quietStartMin >= 24 * 60 ||
        s.quietEndMin < 0 || s.quietEndMin >= 24 * 60) {
      err = "quiet hours must be 0..1439 minutes";
      return false;
    }
  }
  if (!validTimezone(std::string(s.timezone))) {
    err = "bad timezone (use 'auto' or a POSIX TZ string)";
    return false;
  }
  if (!validDeviceName(std::string(s.deviceName))) {
    err = "device name: 1-24 chars, a-z 0-9 hyphen";
    return false;
  }
  if (s.orientation > 3) {
    err = "orientation must be 0..3";
    return false;
  }
  if (s.otaBase[0] && !validImageUrl(std::string(s.otaBase))) {
    err = "OTA base URL must start with http:// or https://";
    return false;
  }
  return true;
}
