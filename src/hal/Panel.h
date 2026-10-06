#pragma once
// Hardware Abstraction: Panel.
//
// Porting to a new panel = subclass this interface (native init sequence
// or a different Seeed_GFX2 product target). The rest of the firmware
// never touches panel pins or controller registers.
#include <Arduino.h>
#include <stdint.h>

struct PanelDims {
  uint16_t width;
  uint16_t height;
};

// Spectra 6 hardware nibble codes (UC8179 family).
enum class Spectra6 : uint8_t {
  White = 0x0,
  Green = 0x2,
  Red = 0x6,
  Yellow = 0xB,
  Blue = 0xD,
  Black = 0xF,
};

class Panel {
 public:
  virtual ~Panel() = default;

  virtual const char* kind() const = 0;  // "gdeb0709e01"
  virtual PanelDims dims() const = 0;
  virtual bool begin() = 0;  // init controller; false on failure
  virtual bool supportsPartial() const = 0;

  // Draw a packed-4bpp framebuffer: 2 px/byte, high nibble first,
  // rows top→bottom, left→right. buf must hold width*height/2 bytes.
  // Blocks for the full refresh (~30 s on Spectra 6).
  virtual bool drawPacked4bpp(const uint8_t* buf, size_t len) = 0;

  // Simple text screen for portal / onboarding / errors.
  virtual bool drawStatus(const char* title, const char* lines[],
                          int numLines) = 0;

  // Setup screen with QR code for the portal URL. Default falls back to
  // drawStatus for panels without QR support.
  virtual bool drawSetupQR(const char* title, const char* apName,
                           const char* url) {
    const char* lines[] = {"1. Join Wi-Fi:", apName, "2. Scan QR or open:",
                           url, "3. Enter Wi-Fi details"};
    return drawStatus(title, lines, 5);
  }

  // Small help QR (bottom-right) for non-photo status screens, drawn into
  // the same framebuffer before the single refresh. Default: no-op for
  // panels without QR support.
  virtual void drawHelpQR() {}

  virtual void sleep() = 0;  // panel low-power mode

  // v2 hook: on-device JPEG decode path. Default: unsupported.
  virtual bool drawJpeg(const uint8_t* /*data*/, size_t /*len*/) {
    return false;
  }
};
