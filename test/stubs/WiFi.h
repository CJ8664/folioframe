#pragma once
#include "Arduino.h"
// Minimal WiFi stub for host-side compile checks. Mirrors only the API
// surface the firmware uses; behavior is not emulated.
class IPAddress {
 public:
  String toString() const { return String("192.168.1.42"); }
};
typedef int WiFiEvent_t;
struct WiFiEventInfo_t {
  struct {
    int reason;
    const char* ssid;
  } wifi_sta_disconnected;
};
#define ARDUINO_EVENT_WIFI_STA_DISCONNECTED 0
#define WL_CONNECTED 3
#define WIFI_AP 2
#define WIFI_STA 1
class WiFiClass {
 public:
  int RSSI() { return 0; }
  IPAddress localIP() { return IPAddress(); }
  IPAddress softAPIP() { return IPAddress(); }
  int status() { return WL_CONNECTED; }
  int getMode() { return WIFI_STA; }
  template <typename F>
  void onEvent(F, WiFiEvent_t) {}
};
extern WiFiClass WiFi;
