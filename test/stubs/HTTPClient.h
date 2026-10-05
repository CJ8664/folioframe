#pragma once
#include "Arduino.h"
#include "WiFiClient.h"
class HTTPClient {
 public:
  void setTimeout(int) {}
  bool begin(const char*) { return true; }
  bool begin(const String&) { return true; }
  bool begin(WiFiClient&, const char*) { return true; }
  bool begin(WiFiClient&, const String&) { return true; }
  void addHeader(const char*, const String&) {}
  void addHeader(const char*, const char*) {}
  int GET() { return 200; }
  int POST(const String&) { return 200; }
  String getString() { return String(""); }
  int getSize() { return 0; }
  WiFiClient* getStreamPtr() { return nullptr; }
  String header(const char*) { return String(""); }
  void end() {}
};
