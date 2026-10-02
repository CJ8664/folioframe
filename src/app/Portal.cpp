#include "Portal.h"

#include <WiFi.h>

bool Portal::ensureWiFi() {
  wm_.setConnectTimeout(30);
  wm_.setConfigPortalTimeout(300);
  String ap = "SF-Setup-" + board_->deviceId();
  return wm_.autoConnect(ap.c_str());
}

int Portal::parseTimeToMin(const String& hhmm) {
  int h = hhmm.substring(0, 2).toInt();
  int m = hhmm.substring(3, 5).toInt();
  return h * 60 + m;
}

String Portal::settingsPage() {
  Settings& s = config_->get();
  char qs[6], qe[6];
  snprintf(qs, sizeof(qs), "%02d:%02d", s.quietStartMin / 60,
           s.quietStartMin % 60);
  snprintf(qe, sizeof(qe), "%02d:%02d", s.quietEndMin / 60, s.quietEndMin % 60);
  const uint32_t opts[] = {15, 30, 60, 120, 240, 480, 720, 1440};
  String intervalOpts;
  for (uint32_t o : opts) {
    intervalOpts += "<option value=\"" + String(o) + "\"" +
                    (o == s.intervalMinutes ? " selected" : "") + ">" +
                    String(o >= 60 ? o / 60 : o) +
                    (o >= 60 ? " h" : " min") + "</option>";
  }
  String h = "<html><body><h2>SpectraFrame settings</h2>"
             "<form method='POST' action='/save'>"
             "Image URL<br><input name='url' size='60' value='" +
             String(s.imageUrl) +
             "'><br><br>Refresh interval<br><select name='interval'>" +
             intervalOpts +
             "</select><br><br>"
             "<input type='checkbox' name='qen' value='1'" +
             (s.quietEnabled ? " checked" : "") +
             "> Quiet hours<br>"
             "Start <input type='time' name='qs' value='" + qs + "'> "
             "End <input type='time' name='qe' value='" + qe +
             "'><br><br>"
             "Timezone (auto or POSIX)<br><input name='tz' value='" +
             String(s.timezone) +
             "'><br><br>"
             "Device name<br><input name='name' value='" +
             String(s.deviceName) +
             "'><br><br>"
             "Orientation (0-3)<br><input name='orient' size='3' value='" +
             String(s.orientation) +
             "'><br><br>"
             "OTA base URL (empty = disabled)<br><input name='otabase' size='40' value='" +
             String(s.otaBase) +
             "'><br><br>"
             "<input type='submit' value='Save'></form>"
             "<p><a href='/debug'>debug JSON</a></p></body></html>";
  return h;
}

void Portal::handleSave() {
  Settings s = config_->get();  // start from current
  strncpy(s.imageUrl, server_.arg("url").c_str(), sizeof(s.imageUrl) - 1);
  s.intervalMinutes = server_.arg("interval").toInt();
  s.quietEnabled = server_.hasArg("qen");
  s.quietStartMin = parseTimeToMin(server_.arg("qs"));
  s.quietEndMin = parseTimeToMin(server_.arg("qe"));
  strncpy(s.timezone, server_.arg("tz").c_str(), sizeof(s.timezone) - 1);
  strncpy(s.deviceName, server_.arg("name").c_str(),
          sizeof(s.deviceName) - 1);
  s.orientation = (uint8_t)server_.arg("orient").toInt();
  strncpy(s.otaBase, server_.arg("otabase").c_str(), sizeof(s.otaBase) - 1);
  String err;
  if (!Config::validate(s, err)) {
    server_.send(400, "text/plain", "Invalid: " + err);
    return;
  }
  config_->get() = s;
  config_->save();
  dirty_ = true;
  server_.send(200, "text/html",
               "<html><body><p>Saved.</p><p><a href='/'>back</a></p></body></html>");
}

void Portal::handleDebug() {
  uint16_t mv = board_->batteryMilliVolts();
  String j = "{\"device\":\"" + board_->deviceId() +
             "\",\"fw\":\"1.0.0\",\"battery_mv\":" + String(mv) +
             ",\"battery_pct\":" + String(board_->batteryPercent()) +
             ",\"rssi\":" + String(WiFi.RSSI()) +
             ",\"uptime_s\":" + String(millis() / 1000) +
             ",\"panel\":\"" + String(board_->info().panelKind) + "\"}";
  server_.send(200, "application/json", j);
}

void Portal::mountDebug(WebServer& server) {
  server.on("/debug", [this]() { handleDebug(); });
}

bool Portal::run(uint32_t timeoutMs) {
  dirty_ = false;
  server_.on("/", [this]() { server_.send(200, "text/html", settingsPage()); });
  server_.on("/save", HTTP_POST, [this]() { handleSave(); });
  mountDebug(server_);
  server_.begin();
  uint32_t start = millis();
  while (millis() - start < timeoutMs) {
    server_.handleClient();
    if (board_->pollButton() == ButtonId::Btn1) break;  // BTN1 exits portal
    delay(10);
  }
  server_.stop();
  return dirty_;
}
