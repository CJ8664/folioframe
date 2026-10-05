#include "OtaManager.h"

#include <HTTPClient.h>
#include <Update.h>
#include <WiFiClientSecure.h>

#include "../../include/board_config.h"

namespace {

bool beginClient(HTTPClient& http, WiFiClientSecure& secure, const String& url,
                 const char* token) {
  http.setTimeout(15000);
  bool ok;
  if (url.startsWith("https://")) {
    // Same documented tradeoff as FrameFetcher: encryption without cert
    // validation. OTA binaries are additionally MD5-checked below when the
    // manifest carries an md5 line.
    secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(url);
  }
  if (!ok) return false;
  if (token && token[0]) http.addHeader("Authorization", String("Bearer ") + token);
  return true;
}

}  // namespace

bool OtaManager::fetchManifest(const char* url, const char* token,
                               spectra::OtaManifest& manifest) {
  HTTPClient http;
  WiFiClientSecure secure;
  if (!beginClient(http, secure, String(url), token)) {
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
  bool ok = spectra::parseOtaManifest(http.getString().c_str(), manifest);
  http.end();
  if (!ok) lastError_ = "bad version manifest";
  return ok;
}

bool OtaManager::flashFirmware(const char* url, const char* token,
                               const spectra::OtaManifest& manifest) {
  HTTPClient http;
  WiFiClientSecure secure;
  if (!beginClient(http, secure, String(url), token)) {
    lastError_ = "firmware fetch failed";
    return false;
  }
  int code = http.GET();
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
  return true;
}

bool OtaManager::checkAndInstall(const char* serverUrl, const char* token,
                                 uint32_t currentBuild) {
  lastError_ = "";

  // Battery gate: never flash on a low battery (brownout lesson).
  uint8_t pct = board_->batteryPercent();
  if (pct > 0 && pct < EE02_OTA_MIN_BATTERY_PCT) {
    lastError_ = "battery too low for OTA";
    return false;
  }

  String base = serverUrl;
  while (base.endsWith("/")) base.remove(base.length() - 1);
  String versionUrl = base + "/v1/device/ota/version";
  String fwUrl = base + "/v1/device/ota/firmware.bin";

  spectra::OtaManifest manifest;
  if (!fetchManifest(versionUrl.c_str(), token, manifest)) {
    if (lastError_.isEmpty()) return false;  // 404: no channel, not an error
    return false;
  }
  if (!spectra::shouldUpdate(currentBuild, manifest)) return false;

  return flashFirmware(fwUrl.c_str(), token, manifest);
}
