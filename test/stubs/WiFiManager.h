#pragma once
#include "Arduino.h"
// Minimal WiFiManager stub for host-side compile checks. Mirrors only the
// API surface the firmware uses; behavior is not emulated.
class WiFiManagerParameter {
 public:
  WiFiManagerParameter(const char*, const char*, const char*, int) {}
  void setValue(const char*, int) {}
  String getValue() { return String(""); }
};
class WiFiManager {
 public:
  void setConnectTimeout(int) {}
  void setConfigPortalTimeout(int) {}
  void setTitle(const char*) {}
  void setCustomHeadElement(const char*) {}
  void addParameter(WiFiManagerParameter*) {}
  bool autoConnect(const char*) { return true; }
  bool getWiFiIsSaved() { return true; }
};
