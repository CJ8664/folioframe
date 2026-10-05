#pragma once
#include "Arduino.h"
class IPAddress {
 public:
  String toString() const { return String("192.168.1.42"); }
};
class WiFiClass {
 public:
  int RSSI() { return 0; }
  IPAddress localIP() { return IPAddress(); }
};
extern WiFiClass WiFi;
