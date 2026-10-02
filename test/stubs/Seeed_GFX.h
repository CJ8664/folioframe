#pragma once
// Stub of the Seeed_GFX2 API surface used by Gdeb0709e01Panel.
#include <stdint.h>

#include "Arduino.h"
struct Seeed_Product {
  static const int Seeed_ePaper_7INCH09_C = 518;
};
class Seeed_GFX {
 public:
  explicit Seeed_GFX(int) {}
  void begin() {}
  void fillScreen(uint16_t) {}
  void drawString(const char*, int, int, int) {}
  void pushImage(int, int, int, int, uint16_t*) {}
  void update() {}
  void sleep() {}
};
