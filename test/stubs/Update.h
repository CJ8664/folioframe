#pragma once
#include "Arduino.h"
#include "WiFiClient.h"
class UpdateClass {
 public:
  bool begin(size_t) { return true; }
  void setMD5(const char*) {}
  size_t writeStream(WiFiClient&) { return 0; }
  bool end(bool) { return true; }
  const char* errorString() { return ""; }
};
extern UpdateClass Update;
