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

String baseUrl(const char* serverUrl) {
  String base = serverUrl;
  while (base.endsWith("/")) base.remove(base.length() - 1);
  return base;
}

}  // namespace

bool OtaManager::batteryGatePassed() {
  // Battery gate: never flash on a low battery (brownout lesson).
  // mv == 0 means no battery / invalid reading: USB-powered or unknown,
  // which is safe to flash on. A valid-but-low reading must NOT flash:
  // batteryPercent() returns 0 both for "unknown" AND for a genuinely
  // dead battery (<=3400mV), so percent alone can't tell them apart.
  uint16_t mv = board_->batteryMilliVolts();
  if (mv == 0) return true;
  return board_->batteryPercent() >= EE02_OTA_MIN_BATTERY_PCT;
}

bool OtaManager::getManifest(const char* serverUrl, const char* token,
                             spectra::OtaManifest& manifest) {
  lastError_ = "";
  HTTPClient http;
  WiFiClientSecure secure;
  String versionUrl = baseUrl(serverUrl) + "/v1/device/ota/version";
  if (!beginClient(http, secure, versionUrl, token)) {
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
                               const spectra::OtaManifest& manifest,
                               OtaProgressCb progress) {
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
    // Update.setMD5() expects a 32-char hex string, not binary bytes.
    // manifest.md5 is already validated as 32 lowercase hex chars by
    // the OtaManifest parser.
    if (!Update.setMD5(manifest.md5.c_str())) {
      lastError_ = "Update.setMD5 failed";
      http.end();
      return false;
    }
  }
  // Chunked write (instead of Update.writeStream) so the UI can report
  // progress. Feeds the same Update MD5 context, so verification is
  // identical.
  WiFiClient* s = http.getStreamPtr();
  static const size_t kChunk = 4096;
  uint8_t* buf = (uint8_t*)malloc(kChunk);
  if (!buf) {
    lastError_ = "no RAM for OTA buffer";
    Update.abort();
    http.end();
    return false;
  }
  size_t written = 0;
  uint8_t lastPct = 0;
  bool ok = true;
  uint32_t stallStart = millis();
  while (written < (size_t)total) {
    int avail = s->available();
    if (avail <= 0) {
      if (millis() - stallStart > 30000) {
        lastError_ = "firmware download stalled";
        ok = false;
        break;
      }
      delay(10);
      continue;
    }
    stallStart = millis();
    size_t toRead = (size_t)avail > kChunk ? kChunk : (size_t)avail;
    int got = s->read(buf, toRead);
    if (got <= 0) {
      lastError_ = "firmware read failed";
      ok = false;
      break;
    }
    if (Update.write(buf, (size_t)got) != (size_t)got) {
      lastError_ = "flash write failed";
      ok = false;
      break;
    }
    written += (size_t)got;
    uint8_t pct = (uint8_t)((written * 100) / (size_t)total);
    if (progress && pct != lastPct) {
      lastPct = pct;
      progress(pct);
    }
  }
  free(buf);
  http.end();
  if (!ok) {
    Update.abort();
    return false;
  }
  if (written != (size_t)total || !Update.end(true)) {
    lastError_ = "flash failed: " + String(Update.errorString());
    return false;
  }
  return true;
}

bool OtaManager::installFromManifest(const char* serverUrl, const char* token,
                                     const spectra::OtaManifest& manifest,
                                     OtaProgressCb progress) {
  lastError_ = "";
  String fwUrl = baseUrl(serverUrl) + "/v1/device/ota/firmware.bin";
  return flashFirmware(fwUrl.c_str(), token, manifest, progress);
}

bool OtaManager::checkAndInstall(const char* serverUrl, const char* token,
                                 uint32_t currentBuild) {
  lastError_ = "";

  if (!batteryGatePassed()) {
    lastError_ = "battery too low for OTA";
    return false;
  }

  spectra::OtaManifest manifest;
  if (!getManifest(serverUrl, token, manifest)) {
    return false;  // 404 (no channel) or a real error; lastError() tells
  }
  if (!spectra::shouldUpdate(currentBuild, manifest)) return false;

  return installFromManifest(serverUrl, token, manifest, nullptr);
}
