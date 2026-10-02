#include "OtaManager.h"

#include <HTTPClient.h>
#include <Update.h>

#include "../../include/board_config.h"

bool OtaManager::checkAndInstall(const char* versionUrl,
                                 const char* firmwareUrl,
                                 uint32_t currentBuild) {
  lastError_ = "";

  // Battery gate: never flash on a low battery (brownout lesson).
  uint8_t pct = board_->batteryPercent();
  if (pct > 0 && pct < EE02_OTA_MIN_BATTERY_PCT) {
    lastError_ = "battery too low for OTA";
    return false;
  }

  HTTPClient http;
  http.setTimeout(15000);
  if (!http.begin(versionUrl)) {
    lastError_ = "version check failed";
    return false;
  }
  int code = http.GET();
  if (code == 404) {
    http.end();
    return false;  // no update channel published
  }
  if (code != 200) {
    lastError_ = "version HTTP " + String(code);
    http.end();
    return false;
  }
  spectra::OtaManifest manifest;
  bool want =
      spectra::parseOtaManifest(http.getString().c_str(), manifest) &&
      spectra::shouldUpdate(currentBuild, manifest);
  http.end();
  if (!want) return false;

  if (!http.begin(firmwareUrl)) {
    lastError_ = "firmware fetch failed";
    return false;
  }
  code = http.GET();
  if (code != 200) {
    lastError_ = "firmware HTTP " + String(code);
    http.end();
    return false;
  }
  int total = http.getSize();
  if (total <= 0) {
    lastError_ = "firmware has no length";
    http.end();
    return false;
  }
  if (!Update.begin(total)) {
    lastError_ = "Update.begin failed";
    http.end();
    return false;
  }
  if (manifest.hasMd5) {
    uint8_t md5[16];
    for (int i = 0; i < 16; i++) {
      char byte[3] = {manifest.md5[2 * i], manifest.md5[2 * i + 1], 0};
      md5[i] = (uint8_t)strtoul(byte, nullptr, 16);
    }
    Update.setMD5((const char*)md5);
  }
  WiFiClient* s = http.getStreamPtr();
  size_t written = Update.writeStream(*s);
  http.end();
  if (written != (size_t)total || !Update.end(true)) {
    lastError_ = "flash failed: " + String(Update.errorString());
    return false;
  }
  return true;  // caller reboots
}
