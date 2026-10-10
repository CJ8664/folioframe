#pragma once
#include "Arduino.h"
#include "WiFiClient.h"
class UpdateClass {
 public:
  bool begin(size_t) { return true; }
  bool setMD5(const char*) { return true; }
  size_t write(uint8_t*, size_t) { return 0; }
  size_t writeStream(WiFiClient&) { return 0; }
  void abort() {}
  bool end(bool) { return true; }
  const char* errorString() { return ""; }
};
extern UpdateClass Update;
