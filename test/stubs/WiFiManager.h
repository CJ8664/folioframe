#pragma once
#include "Arduino.h"
class WiFiManager {
 public:
  void setConnectTimeout(int) {}
  void setConfigPortalTimeout(int) {}
  bool autoConnect(const char*) { return true; }
};
