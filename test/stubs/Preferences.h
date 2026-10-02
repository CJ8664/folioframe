#pragma once
#include "Arduino.h"
class Preferences {
 public:
  bool begin(const char*, bool) { return true; }
  void end() {}
  size_t getString(const char*, char*, size_t) { return 0; }
  void putString(const char*, const char*) {}
  uint32_t getUInt(const char*, uint32_t d) { return d; }
  void putUInt(const char*, uint32_t) {}
  bool getBool(const char*, bool d) { return d; }
  void putBool(const char*, bool) {}
  int getInt(const char*, int d) { return d; }
  void putInt(const char*, int) {}
  uint8_t getUChar(const char*, uint8_t d) { return d; }
  void putUChar(const char*, uint8_t) {}
};
