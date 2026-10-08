#include "DeviceClient.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

void DeviceClient::begin(const char* serverUrl, const char* fwVersion) {
  serverUrl_ = serverUrl;
  // Tolerate a trailing slash in settings; paths are appended below.
  while (serverUrl_.endsWith("/"))
    serverUrl_.remove(serverUrl_.length() - 1);
  fwVersion_ = fwVersion;
}

int DeviceClient::postJson(const char* path, const String& jsonBody,
                           const char* token, String& bodyOut) {
  lastError_ = "";
  bodyOut = "";
  String url = serverUrl_ + path;
  HTTPClient http;
  http.setTimeout(15000);
  WiFiClientSecure secure;
  bool ok;
  if (url.startsWith("https://")) {
    // Same documented tradeoff as FrameFetcher: the ESP32-S3 has no
    // maintained CA bundle here, so TLS is encryption-only. Pair over a
    // server you trust (ideally your own LAN host or tunnel).
    secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(url);
  }
  if (!ok) {
    lastError_ = "http.begin failed";
    return -1;
  }
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Id", board_->deviceId());
  http.addHeader("X-Firmware-Version", fwVersion_);
  if (token && token[0]) {
    http.addHeader("Authorization", String("Bearer ") + token);
  }
  int code = http.POST(jsonBody);
  if (code >= 200 && code < 300) bodyOut = http.getString();
  http.end();
  return code;
}

RegisterResult DeviceClient::registerDevice() {
  RegisterResult r;
  String body;
  String payload = "{\"device_id\":\"" + board_->deviceId() +
                   "\",\"panel\":\"" + String(board_->info().panelKind) +
                   "\",\"fw\":\"" + fwVersion_ + "\"}";
  int code = postJson("/v1/device/register", payload, nullptr, body);
  if (code == 429) {
    r.err = "rate limited, try again soon";
    return r;
  }
  if (code != 201 || !spectra::jsonOk(body.c_str())) {
    r.err = code < 0 ? lastError_ : "register HTTP " + String(code);
    return r;
  }
  std::string cc = spectra::jsonString(body.c_str(), "claim_code");
  if (cc.empty()) {
    r.err = "bad register response";
    return r;
  }
  r.ok = true;
  r.claimCode = String(cc.c_str());
  // expires_in is a JSON number; parse leniently, fall back to 10 min.
  r.expiresInSec = 600;
  int kp = body.indexOf("\"expires_in\"");
  if (kp >= 0) {
    int cp = body.indexOf(':', (unsigned int)kp);
    if (cp >= 0) {
      int v = body.substring((unsigned int)cp + 1).toInt();
      if (v > 0 && v <= 3600) r.expiresInSec = v;
    }
  }
  return r;
}

ClaimResult DeviceClient::pollClaim(const char* claimCode) {
  ClaimResult r;
  String body;
  String payload = "{\"device_id\":\"" + board_->deviceId() +
                   "\",\"claim_code\":\"" + String(claimCode) + "\"}";
  int code = postJson("/v1/device/claim", payload, nullptr, body);
  if (code != 200 || !spectra::jsonOk(body.c_str())) {
    r.err = code < 0 ? lastError_ : "claim HTTP " + String(code);
    return r;
  }
  std::string st = spectra::jsonString(body.c_str(), "status");
  if (st == "claimed") {
    std::string tok = spectra::jsonString(body.c_str(), "device_token");
    if (tok.empty()) {
      r.err = "claimed but no token";
      return r;
    }
    r.state = ClaimState::Claimed;
    r.token = String(tok.c_str());
  } else {
    // "pending" -- and deliberately the same shape when the code is
    // wrong or expired (the server gives no guessing oracle).
    r.state = ClaimState::Pending;
  }
  return r;
}

bool DeviceClient::unpair(const char* token) {
  String body;
  int code = postJson("/v1/device/unpair", "{}", token, body);
  return code == 200;
}

bool DeviceClient::sendStatus(const char* token, uint32_t fwBuild) {
  String body;
  String payload = "{\"fw\":\"" + fwVersion_ + "\",\"fw_build\":" +
                   String(fwBuild) + ",\"battery_pct\":" +
                   String(board_->batteryPercent()) + ",\"rssi\":" +
                   String(WiFi.RSSI()) + "}";
  int code = postJson("/v1/device/status", payload, token, body);
  lastStatusBody_ = body;
  return code == 200;
}

bool DeviceClient::lastAutoUpdate(bool dflt) const {
  if (lastStatusBody_.isEmpty()) return dflt;
  std::string body(lastStatusBody_.c_str());
  // Distinguish "server sent no setting" from "server sent false": only
  // override when the key is actually present.
  size_t p = body.find("\"auto_update\"");
  if (p == std::string::npos) return dflt;
  return spectra::jsonNestedBool(body, "settings", "auto_update", dflt);
}
