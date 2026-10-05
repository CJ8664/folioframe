#pragma once
// Captive-portal Wi-Fi provisioning (WiFiManager) + single-page settings
// portal + /debug JSON + /unpair. Run when: no Wi-Fi credentials, no server
// URL configured, or user holds BTN1.
//
// First-boot setup is a single screen: the Wi-Fi captive portal also asks
// for the server URL (WiFiManagerParameter), so the user never has to hunt
// down the frame's LAN IP. The LAN settings portal remains as a fallback
// when the URL is left blank or needs changing later.
#include <Arduino.h>
#include <WebServer.h>
#include <WiFiManager.h>

#include "../hal/Board.h"
#include "Config.h"
#include "DeviceClient.h"

class Portal {
 public:
  Portal(Board* board, Config* config, DeviceClient* client)
      : board_(board),
        config_(config),
        client_(client),
        serverParam_("srv", "Server URL", "", 256) {}

  // Ensure Wi-Fi is connected (blocking, with portal fallback).
  // Also captures the server URL from the captive portal when shown.
  bool ensureWiFi();

  // True when Wi-Fi credentials are stored (i.e. ensureWiFi will not need
  // to start the setup AP).
  bool hasWiFiCreds();

  // Run the settings portal until timeout or BTN1 press. Returns true if
  // any setting changed (caller should re-fetch before sleeping).
  bool run(uint32_t timeoutMs);

  // Serve the /debug JSON on demand (also mounted in run()).
  void mountDebug(WebServer& server);

 private:
  Board* board_;
  Config* config_;
  DeviceClient* client_;  // for /unpair; may be used before begin()
  WiFiManager wm_;
  WebServer server_{80};
  bool dirty_ = false;
  WiFiManagerParameter serverParam_;  // server URL field on the Wi-Fi portal
  bool serverParamAdded_ = false;

  String settingsPage();
  void handleSave();
  void handleUnpair();
  void handleDebug();
  // Persist the server URL typed into the Wi-Fi captive portal (if any).
  void saveServerUrlFromPortal();
  static int parseTimeToMin(const String& hhmm);
};
