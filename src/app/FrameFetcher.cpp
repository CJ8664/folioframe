#include "FrameFetcher.h"

#include <HTTPClient.h>
#include <WiFiClientSecure.h>

FrameFetcher::FrameFetcher(Board* board, Panel* panel)
    : board_(board), panel_(panel) {}

bool FrameFetcher::begin() {
  PanelDims d = panel_->dims();
  bufSize_ = (size_t)d.width * d.height / 2;
  buf_ = (uint8_t*)ps_malloc(bufSize_);
  return buf_ != nullptr;
}

FetchResult FrameFetcher::fetchFrame(const char* serverUrl, const char* token,
                                     const char* fwVersion, const char* etag) {
  lastError_ = "";
  len_ = 0;
  String url = String(serverUrl);
  while (url.endsWith("/")) url.remove(url.length() - 1);
  url += "/v1/device/frame";

  HTTPClient http;
  http.setTimeout(20000);
  WiFiClientSecure secure;
  bool ok;
  if (url.startsWith("https://")) {
    // Documented tradeoff (sven97, matthewfcarlson): no cert validation on
    // the device; use the companion server or a pinned local host for privacy.
    secure.setInsecure();
    ok = http.begin(secure, url);
  } else {
    ok = http.begin(url);
  }
  if (!ok) {
    lastError_ = "http.begin failed";
    return FetchResult::Error;
  }
  http.addHeader("Authorization", String("Bearer ") + token);
  http.addHeader("X-Device-Id", board_->deviceId());
  http.addHeader("X-Device-Panel", board_->info().panelKind);
  PanelDims d = panel_->dims();
  http.addHeader("X-Device-Width", String(d.width));
  http.addHeader("X-Device-Height", String(d.height));
  http.addHeader("X-Firmware-Version", fwVersion);
  uint16_t mv = board_->batteryMilliVolts();
  if (mv > 0) {
    http.addHeader("X-Battery-Mv", String(mv));
    http.addHeader("X-Battery-Pct", String(board_->batteryPercent()));
  }
  if (etag && etag[0]) http.addHeader("If-None-Match", etag);
  // ETag is read after the transfer; without collectHeaders() the
  // Arduino client discards it and every fetch repaints.
  const char* headerKeys[] = {"ETag"};
  http.collectHeaders(headerKeys, 1);

  int code = http.GET();
  if (code == 304) {
    http.end();
    return FetchResult::NotModified;
  }
  if (code == 401) {
    // Token revoked or never valid: the server owner unpaired us, or the
    // token in NVS is corrupt. Caller clears it and re-pairs.
    lastError_ = "unauthorized (re-pair needed)";
    http.end();
    return FetchResult::Unauthorized;
  }
  if (code != 200) {
    lastError_ = "HTTP " + String(code);
    http.end();
    return FetchResult::Error;
  }
  int clen = http.getSize();
  if (clen != (int)bufSize_) {
    lastError_ = "bad frame size " + String(clen);
    http.end();
    return FetchResult::Error;  // refuse to paint garbage
  }
  WiFiClient* s = http.getStreamPtr();
  size_t got = 0;
  uint32_t lastRx = millis();
  while (got < bufSize_) {
    int avail = s->available();
    if (avail > 0) {
      size_t n = s->readBytes(buf_ + got, bufSize_ - got);
      got += n;
      lastRx = millis();
    } else if (millis() - lastRx > 20000) {
      lastError_ = "transfer stall";
      http.end();
      return FetchResult::Error;
    } else {
      delay(5);
    }
  }
  etag_ = http.header("ETag");
  len_ = got;
  http.end();
  return FetchResult::Ok;
}
