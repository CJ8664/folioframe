#pragma once
// Captive-portal Wi-Fi provisioning (WiFiManager) + single-page settings
// portal + /debug JSON. Run when: no Wi-Fi credentials, or user holds BTN1.
#include <Arduino.h>
#include <WebServer.h>
#include <WiFiManager.h>

#include "../hal/Board.h"
#include "Config.h"

class Portal {
 public:
  Portal(Board* board, Config* config) : board_(board), config_(config) {}

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
  WiFiManager wm_;
  WebServer server_{80};
  bool dirty_ = false;

  String settingsPage();
  void handleSave();
  void handleDebug();
  static int parseTimeToMin(const String& hhmm);
};
