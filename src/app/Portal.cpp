#include "Portal.h"

#include <WiFi.h>

namespace {
// HTML-escape a user- or device-controlled string before interpolating it
// into the portal HTML. Values like the server URL, timezone, device name,
// and OTA base URL are typed by the user (or come from the device) and would
// otherwise break out of the input value='...' attribute or inject markup
// into the settings page.
String escapeHtml(const String& in) {
  String out;
  const char* p = in.c_str();
  for (size_t i = 0; p[i]; i++) {
    switch (p[i]) {
      case '&':
        out += "&amp;";
        break;
      case '<':
        out += "&lt;";
        break;
      case '>':
        out += "&gt;";
        break;
      case '"':
        out += "&quot;";
        break;
      case '\'':
        out += "&#39;";
        break;
      default: {
        char ch[2] = {p[i], '\0'};
        out += ch;
        break;
      }
    }
  }
  return out;
}
}  // namespace

bool Portal::ensureWiFi() {
  wm_.setConnectTimeout(30);
  wm_.setConfigPortalTimeout(300);
  // Ask for the server URL on the same captive-portal screen as the Wi-Fi
  // credentials: one setup step instead of two. Pre-fill the saved value so
  // re-running the portal never wipes it.
  serverParam_.setValue(config_->get().serverUrl,
                        sizeof(config_->get().serverUrl));
  if (!serverParamAdded_) {
    wm_.addParameter(&serverParam_);
    serverParamAdded_ = true;
  }
  String ap = "FF-Setup-" + board_->deviceId();
  bool ok = wm_.autoConnect(ap.c_str());
  if (ok) saveServerUrlFromPortal();
  return ok;
}

void Portal::saveServerUrlFromPortal() {
  String srv = serverParam_.getValue();
  srv.trim();
  Settings& s = config_->get();
  if (srv == String(s.serverUrl)) return;  // unchanged (or still blank)
  Settings cand = s;  // validate the full record, same as the /save handler
  strncpy(cand.serverUrl, srv.c_str(), sizeof(cand.serverUrl) - 1);
  cand.serverUrl[sizeof(cand.serverUrl) - 1] = '\0';
  String err;
  if (!Config::validate(cand, err)) {
    Serial.printf("portal server URL rejected: %s\n", err.c_str());
    return;  // keep the old value; the LAN settings portal still enforces it
  }
  // Changing servers invalidates the pairing token, same as /save.
  if (String(s.serverUrl) != srv) config_->clearDeviceToken();
  s = cand;
  config_->save();
  dirty_ = true;
}

bool Portal::hasWiFiCreds() { return wm_.getWiFiIsSaved(); }

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
  String h = "<html><body><h2>FolioFrame settings</h2>"
             "<form method='POST' action='/save'>"
             "Server URL<br><input name='srv' size='60' value='" +
             escapeHtml(String(s.serverUrl)) +
             "' placeholder='https://frame.example.com'><br>"
             "<small>Your FolioFrame server. The frame pairs with it and "
             "fetches images from it.</small><br><br>"
             "Refresh interval<br><select name='interval'>" +
             intervalOpts +
             "</select><br><br>"
             "<input type='checkbox' name='qen' value='1'" +
             (s.quietEnabled ? " checked" : "") +
             "> Quiet hours<br>"
             "Start <input type='time' name='qs' value='" + qs + "'> "
             "End <input type='time' name='qe' value='" + qe +
             "'><br><br>"
             "Timezone (auto or POSIX)<br><input name='tz' value='" +
             escapeHtml(String(s.timezone)) +
             "'><br><br>"
             "Device name<br><input name='name' value='" +
             escapeHtml(String(s.deviceName)) +
             "'><br><br>"
             "Orientation (0-3)<br><input name='orient' size='3' value='" +
             String(s.orientation) +
             "'><br><br>"
             "OTA base URL (empty = use server)<br><input name='otabase' size='40' value='" +
             escapeHtml(String(s.otaBase)) +
             "'><br><br>"
             "<input type='checkbox' name='otaauto' value='1'" +
             (s.otaAutoInstall ? " checked" : "") +
             "> Install firmware updates automatically<br>"
             "<small>When on, the frame installs updates quietly on its own. "
             "When off, it only lets you know an update is ready, and you "
             "install it with the frame's buttons.</small><br><br>"
             "<input type='submit' value='Save'></form>"
             "<p><a href='/debug'>debug JSON</a></p>"
             "<p><form method='POST' action='/unpair' "
             "onsubmit=\"return confirm('Unpair this frame? It will need to "
             "be paired again.')\">"
             "<input type='submit' value='Unpair frame'></form></p>"
             "</body></html>";
  return h;
}

void Portal::handleSave() {
  Settings s = config_->get();  // start from current
  String newSrv = server_.arg("srv");
  newSrv.trim();
  strncpy(s.serverUrl, newSrv.c_str(), sizeof(s.serverUrl) - 1);
  s.serverUrl[sizeof(s.serverUrl) - 1] = '\0';
  // Changing servers invalidates the pairing token: it belongs to the old
  // server. Force a re-pair rather than failing every fetch with 401s.
  if (String(config_->get().serverUrl) != String(s.serverUrl)) {
    config_->clearDeviceToken();
  }
  s.intervalMinutes = server_.arg("interval").toInt();
  s.quietEnabled = server_.hasArg("qen");
  s.quietStartMin = parseTimeToMin(server_.arg("qs"));
  s.quietEndMin = parseTimeToMin(server_.arg("qe"));
  strncpy(s.timezone, server_.arg("tz").c_str(), sizeof(s.timezone) - 1);
  s.timezone[sizeof(s.timezone) - 1] = '\0';
  strncpy(s.deviceName, server_.arg("name").c_str(),
          sizeof(s.deviceName) - 1);
  s.deviceName[sizeof(s.deviceName) - 1] = '\0';
  s.orientation = (uint8_t)server_.arg("orient").toInt();
  strncpy(s.otaBase, server_.arg("otabase").c_str(), sizeof(s.otaBase) - 1);
  s.otaBase[sizeof(s.otaBase) - 1] = '\0';
  s.otaAutoInstall = server_.hasArg("otaauto");
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

void Portal::handleUnpair() {
  String token = config_->deviceToken();
  bool ok = true;
  if (token.length() && client_) ok = client_->unpair(token.c_str());
  config_->clearDeviceToken();
  dirty_ = true;  // caller re-boots into pairing mode
  server_.send(200, "text/html",
               ok ? "<html><body><p>Unpaired. The frame will show a new "
                    "pairing code on next wake.</p></body></html>"
                  : "<html><body><p>Server unreachable, but the local token "
                    "was cleared. Re-pair on next wake.</p></body></html>");
}

void Portal::handleDebug() {
  uint16_t mv = board_->batteryMilliVolts();
  String j = "{\"device\":\"" + board_->deviceId() +
             "\",\"fw\":\"" + client_->fwVersion() + "\",\"battery_mv\":" + String(mv) +
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
  server_.on("/unpair", HTTP_POST, [this]() { handleUnpair(); });
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
