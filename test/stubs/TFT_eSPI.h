#pragma once
#include <stdint.h>
#include "Arduino.h"
// Minimal TFT_eSPI stub for host-side compile checks. Mirrors only the API
// surface the firmware uses; behavior is not emulated.
#define TFT_BLACK 0x0000
#define TFT_WHITE 0xFFFF
// The real build defines this in src/User_Setup.h (GPIO44 = panel CS).
// The firmware #errors if it isn't the literal 44; keep the stub honest.
#ifndef TFT_CS
#define TFT_CS 44
#endif
class TFT_eSprite {
 public:
  void fillRect(int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void drawRect(int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void fillRoundRect(int32_t, int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void drawRoundRect(int32_t, int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void fillCircle(int32_t, int32_t, int32_t, uint32_t) {}
  void drawCircle(int32_t, int32_t, int32_t, uint32_t) {}
  void drawTriangle(int32_t, int32_t, int32_t, int32_t, int32_t, int32_t,
                    uint32_t) {}
  void drawLine(int32_t, int32_t, int32_t, int32_t, uint32_t) {}
  void drawString(const String&, int32_t, int32_t, uint8_t) {}
  void setTextColor(uint32_t) {}
  void setTextDatum(uint8_t) {}
  void setTextSize(uint8_t) {}
};
// Seeed_GFX (v1) EPaper panel driver: a TFT_eSprite subclass in the real
// library. Stubbed here for host-side compile checks only.
class EPaper : public TFT_eSprite {
 public:
  void begin() {}
  void sleep() {}
  void update() {}
  void pushImage(int32_t, int32_t, int32_t, int32_t, const uint16_t*) {}
};
