#include "Portal.h"

#include <HTTPClient.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

// Warm Clay portal theme + client-side validation, injected into the
// WiFiManager captive-portal <head>. Vanilla JS only: the portal often
// renders in the phone's captive-portal mini-browser, not full Chrome.
static const char kPortalHeadHtml[] = R"HTML(
<style>
body{background:#ece5d8;color:#2f302a;font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text",system-ui,sans-serif;margin:0;padding:16px;line-height:1.45}
h1,h2,h3{color:#2f302a}
input,select{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border:1px solid #d8cdbc;border-radius:12px;font-size:16px;background:#fffaf1;color:#2f302a}
input:focus,select:focus{outline:2px solid #c1663e;border-color:#c1663e}
button,input[type=submit]{background:#c1663e;color:#fffaf1;border:0;border-radius:12px;padding:14px;font-size:16px;font-weight:600;width:100%;margin:10px 0;cursor:pointer}
button:active,input[type=submit]:active{background:#9e4c2e}
a{color:#c1663e}
.ff-brand{text-align:center;margin:6px 0 18px}
.ff-brand h1{margin:0;font-size:26px;letter-spacing:.5px}
.ff-brand p{margin:6px 0 0;color:#69685d;font-size:14px}
.ff-help{font-size:13px;color:#69685d;margin:2px 0 10px}
.ff-err{display:none;background:#fbe7e7;border:1px solid #d98a8a;color:#8f1d1d;border-radius:12px;padding:10px 12px;margin:8px 0;font-size:14px}
label{font-weight:600;font-size:14px}
</style>
<script>
(function(){
function onReady(fn){if(document.readyState!=='loading'){fn();}else{document.addEventListener('DOMContentLoaded',fn);}}
onReady(function(){
  var b=document.createElement('div');b.className='ff-brand';
  b.innerHTML='<h1>FolioFrame</h1><p>Connect your frame to Wi-Fi</p>';
  if(document.body.firstChild){document.body.insertBefore(b,document.body.firstChild);}else{document.body.appendChild(b);}
  var srv=document.getElementById('srv');
  if(!srv)return;
  var help=document.createElement('div');help.className='ff-help';
  help.textContent='Your FolioFrame server address, e.g. https://frame.example.com. The frame pairs with it and fetches photos from it.';
  srv.parentNode.insertBefore(help,srv.nextSibling);
  var err=document.createElement('div');err.className='ff-err';
  help.parentNode.insertBefore(err,help.nextSibling);
  var form=srv.form||document.querySelector('form');
  if(!form)return;
  form.addEventListener('submit',function(e){
    var v=srv.value.trim();var msg='';
    if(!v){msg='Please enter your FolioFrame server URL.';}
    else if(!/^https?:\/\/[^\/\s]+/.test(v)){msg='That doesn\u2019t look like a URL \u2014 start with http:// or https://';}
    if(msg){e.preventDefault();err.textContent=msg;err.style.display='block';srv.focus();window.scrollTo(0,0);}
  });
});
})();
</script>
)HTML";

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
  wm_.setTitle("FolioFrame Setup");
  wm_.setCustomHeadElement(kPortalHeadHtml);
  // Diagnostic: log the 802.11 disconnect reason code on every STA
  // disconnect (e.g. 201=NO_AP_FOUND, 202=AUTH_FAIL, 15=handshake timeout).
  // WiFiManager also logs this at verbose debug level; this is unconditional.
  static bool diagHooked = false;
  if (!diagHooked) {
    WiFi.onEvent(
        [](WiFiEvent_t event, WiFiEventInfo_t info) {
          if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
            Serial.printf("wifi diag: disconnected reason=%d from %s\n",
                          info.wifi_sta_disconnected.reason,
                          info.wifi_sta_disconnected.ssid);
          }
        },
        ARDUINO_EVENT_WIFI_STA_DISCONNECTED);
    diagHooked = true;
  }
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
  // Save the server URL independently of the Wi-Fi result: a failed Wi-Fi
  // attempt must never eat the typed URL (it did before 0.0.16).
  saveServerUrlFromPortal();
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
  // Ping-verify when we're online: only accept URLs that answer as a
  // FolioFrame server. Offline we can't check, so save anyway — losing the
  // typing was the worse bug, and pairing re-verifies reachability later.
  if (WiFi.status() == WL_CONNECTED && !verifyServerUrl(srv)) {
    Serial.printf("portal server URL did not verify, not saving: %s\n",
                  srv.c_str());
    return;
  }
  // Changing servers invalidates the pairing token, same as /save.
  if (String(s.serverUrl) != srv) config_->clearDeviceToken();
  s = cand;
  config_->save();
  dirty_ = true;
}

bool Portal::verifyServerUrl(const String& url) {
  String probe = url;
  while (probe.endsWith("/")) probe.remove(probe.length() - 1);
  probe += "/flash/manifest.json";
  Serial.printf("verifying server URL: %s\n", probe.c_str());
  HTTPClient http;
  http.setTimeout(6000);
  WiFiClientSecure secure;
  bool begun;
  if (probe.startsWith("https://")) {
    // Same documented tradeoff as DeviceClient: encryption without CA
    // verification on the ESP32-S3.
    secure.setInsecure();
    begun = http.begin(secure, probe);
  } else {
    begun = http.begin(probe);
  }
  if (!begun) return false;
  int code = http.GET();
  bool ok = false;
  if (code == 200) {
    ok = http.getString().indexOf("FolioFrame") >= 0;
  } else {
    Serial.printf("server URL verify: HTTP %d\n", code);
  }
  http.end();
  return ok;
}

bool Portal::hasWiFiCreds() { return wm_.getWiFiIsSaved(); }

String Portal::settingsPage() {
  // Slim local portal: Wi-Fi + server URL are captured on the WiFiManager
  // setup screen; every other device setting lives on the FolioFrame
  // website once the frame is paired (the device pulls them each wake).
  // Only the server URL (bootstrap) and the local-dev OTA base override
  // remain here.
  Settings& s = config_->get();
  String h =
      "<html><head><meta name='viewport' content='width=device-width,initial-scale=1'>"
      "<style>"
      "body{background:#ece5d8;color:#2f302a;font-family:-apple-system,BlinkMacSystemFont,"
      "\"SF Pro Text\",system-ui,sans-serif;margin:0;padding:16px;line-height:1.45}"
      "h2{color:#2f302a}"
      "input{width:100%;box-sizing:border-box;padding:12px;margin:6px 0;border:1px solid #d8cdbc;"
      "border-radius:12px;font-size:16px;background:#fffaf1;color:#2f302a}"
      "input:focus{outline:2px solid #c1663e;border-color:#c1663e}"
      "input[type=submit]{background:#c1663e;color:#fffaf1;border:0;font-weight:600;cursor:pointer}"
      "input[type=submit]:active{background:#9e4c2e}"
      "a{color:#c1663e}"
      ".ff-help{font-size:13px;color:#69685d;margin:2px 0 10px}"
      ".ff-err{display:none;background:#fbe7e7;border:1px solid #d98a8a;color:#8f1d1d;"
      "border-radius:12px;padding:10px 12px;margin:8px 0;font-size:14px}"
      ".ff-brand{text-align:center;margin:6px 0 18px}"
      ".ff-brand h1{margin:0;font-size:26px}"
      ".ff-brand p{margin:6px 0 0;color:#69685d;font-size:14px}"
      "label{font-weight:600;font-size:14px}"
      "</style></head><body>"
      "<div class='ff-brand'><h1>FolioFrame</h1><p>Frame settings</p></div>"
      "<form method='POST' action='/save' id='ff-settings'>"
      "<input type='hidden' name='csrf' value='" +
      csrfToken_ +
      "'>"
      "<label for='ff-srv'>Server URL</label><br>"
      "<input name='srv' id='ff-srv' size='60' value='" +
      escapeHtml(String(s.serverUrl)) +
      "' placeholder='https://frame.example.com'>"
      "<div class='ff-help'>Your FolioFrame server. The frame pairs with it and "
      "fetches photos from it. The address is verified before saving.</div>"
      "<div class='ff-err' id='ff-srv-err'></div>"
      "<label for='ff-otabase'>OTA base URL (empty = use server)</label><br>"
      "<input name='otabase' id='ff-otabase' size='40' value='" +
      escapeHtml(String(s.otaBase)) +
      "'><br><br>"
      "<input type='submit' value='Save'></form>"
      "<script>(function(){var f=document.getElementById('ff-settings');if(!f)return;"
      "var srv=document.getElementById('ff-srv');var err=document.getElementById('ff-srv-err');"
      "f.addEventListener('submit',function(e){var v=srv.value.trim();var msg='';"
      "if(!v){msg='Please enter your FolioFrame server URL.';}"
      "else if(!/^https?:\\/\\/[^\\/\\s]+/.test(v)){msg='That doesn\\u2019t look like a URL.';}"
      "if(msg){e.preventDefault();err.textContent=msg;err.style.display='block';srv.focus();}});})();</script>"
      "<p class='ff-help'>Photo refresh, quiet hours, timezone and other settings "
      "live on the FolioFrame website once this frame is paired.</p>"
      "<p><a href='/debug'>debug JSON</a></p>"
      "<p><form method='POST' action='/unpair' "
      "onsubmit=\"return confirm('Unpair this frame? It will need to "
      "be paired again.')\">"
      "<input type='hidden' name='csrf' value='" +
      csrfToken_ +
      "'>"
      "<input type='submit' value='Unpair frame'></form></p>"
      "</body></html>";
  return h;
}

void Portal::handleSave() {
  if (!checkCsrf()) {
    server_.send(403, "text/plain", "CSRF token missing or invalid");
    return;
  }
  // Slim form: only the server URL and the local-dev OTA base override are
  // editable here now. Every other device setting lives on the website;
  // the untouched fields keep their current values.
  Settings s = config_->get();  // start from current
  String newSrv = server_.arg("srv");
  newSrv.trim();
  if (!newSrv.length()) {
    server_.send(400, "text/plain", "Server URL is required.");
    return;
  }
  strncpy(s.serverUrl, newSrv.c_str(), sizeof(s.serverUrl) - 1);
  s.serverUrl[sizeof(s.serverUrl) - 1] = '\0';
  // Changing servers invalidates the pairing token: it belongs to the old
  // server. Force a re-pair rather than failing every fetch with 401s.
  if (String(config_->get().serverUrl) != String(s.serverUrl)) {
    config_->clearDeviceToken();
  }
  strncpy(s.otaBase, server_.arg("otabase").c_str(), sizeof(s.otaBase) - 1);
  s.otaBase[sizeof(s.otaBase) - 1] = '\0';
  String err;
  if (!Config::validate(s, err)) {
    server_.send(400, "text/plain", "Invalid: " + err);
    return;
  }
  // Ping-verify: only accept URLs that answer as a FolioFrame server.
  if (!verifyServerUrl(newSrv)) {
    server_.send(400, "text/plain",
                 "That URL didn't answer as a FolioFrame server. Check the "
                 "address and try again.");
    return;
  }
  config_->get() = s;
  config_->save();
  dirty_ = true;
  server_.send(200, "text/html",
               "<html><body><p>Saved.</p><p><a href='/'>back</a></p></body></html>");
}
void Portal::handleUnpair() {
  if (!checkCsrf()) {
    server_.send(403, "text/plain", "CSRF token missing or invalid");
    return;
  }
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

bool Portal::checkCsrf() {
  // Constant-time compare isn't critical here (token is per-boot random),
  // but avoid trivial timing leaks anyway.
  String got = server_.arg("csrf");
  if (got.length() != csrfToken_.length()) return false;
  for (size_t i = 0; i < got.length(); i++) {
    if (got[i] != csrfToken_[i]) return false;
  }
  return true;
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
  // Fresh CSRF token per portal session: POSTs to /save and /unpair must
  // carry it, or they're rejected. Blocks CSRF from malicious LAN pages.
  csrfToken_ = String(esp_random(), HEX) + String(esp_random(), HEX);
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
