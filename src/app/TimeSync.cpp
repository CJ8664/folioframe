#include "TimeSync.h"

#include <HTTPClient.h>

static const uint32_t kNtpTimeoutMs = 15000;

bool TimeSync::begin(const char* tzSetting) {
  String tz = tzSetting;
  if (tz == "auto") {
    if (!fetchIpApiOffset()) {
      setenv("TZ", "UTC0", 1);
      offsetMin_ = 0;
    } else {
      // POSIX sign is inverted: UTC-8 -> "UTC8". Keep the minutes for
      // half-hour zones (e.g. UTC+5:30 -> "UTC-5:30").
      char buf[16];
      int hrs = offsetMin_ / 60;
      int mins = abs(offsetMin_ % 60);
      if (mins == 0)
        snprintf(buf, sizeof(buf), "UTC%ld", -(long)hrs);
      else
        snprintf(buf, sizeof(buf), "UTC%ld:%02d", -(long)hrs, mins);
      setenv("TZ", buf, 1);
    }
  } else {
    setenv("TZ", tz.c_str(), 1);
    offsetMin_ = 0;  // unknown for custom POSIX strings; scheduler uses
                     // localtime() directly via mktime in that path
  }
  tzset();
  configTime(0, 0, "pool.ntp.org", "time.google.com");
  uint32_t start = millis();
  time_t now = 0;
  while (now < 1577836800 && (millis() - start) < kNtpTimeoutMs) {  // 2020-01-01
    delay(200);
    time(&now);
  }
  return now >= 1577836800;
}

bool TimeSync::fetchIpApiOffset() {
  // Plain HTTP by necessity: ip-api.com's free tier has no HTTPS. The
  // response only sets the quiet-hours UTC offset (fail-safe: falls back
  // to UTC), never anything security-sensitive. A MITM can at worst shift
  // the sleep schedule.
  HTTPClient http;
  http.setTimeout(8000);
  if (!http.begin("http://ip-api.com/json/?fields=status,offset")) return false;
  int code = http.GET();
  if (code != 200) {
    http.end();
    return false;
  }
  String body = http.getString();
  http.end();
  // Minimal parse: {"status":"success","offset":-25200}
  if (body.indexOf("\"status\":\"success\"") < 0) return false;
  int idx = body.indexOf("\"offset\":");
  if (idx < 0) return false;
  offsetMin_ = body.substring(idx + 9).toInt() / 60;
  return true;
}
