#pragma once
// Captive-portal Wi-Fi provisioning (WiFiManager) + single-page settings
// portal + /debug JSON + /unpair. Run when: no Wi-Fi credentials, no server
// URL configured, or user holds BTN1.
#include <Arduino.h>
#include <WebServer.h>
#include <WiFiManager.h>

#include "../hal/Board.h"
#include "Config.h"
#include "DeviceClient.h"

class Portal {
 public:
  Portal(Board* board, Config* config, DeviceClient* client)
      : board_(board), config_(config), client_(client) {}

  // Ensure Wi-Fi is connected (blocking, with portal fallback).
  bool ensureWiFi();

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

  String settingsPage();
  void handleSave();
  void handleUnpair();
  void handleDebug();
  static int parseTimeToMin(const String& hhmm);
};
