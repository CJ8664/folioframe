#pragma once
#include "Arduino.h"
class WiFiClient {
 public:
  virtual int available() { return 0; }
  virtual size_t readBytes(uint8_t*, size_t) { return 0; }
  virtual ~WiFiClient() = default;
};
