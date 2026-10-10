#pragma once
#include "Panel.h"

// 7.09" Good Display GDEB0709E01 via the official Seeed_GFX2 library.
// Panel target: Seeed_Product::Seeed_ePaper_7INCH09_C (PSRAM must be enabled).
// If Seeed renames the enum, this is the single line that changes.
class Gdeb0709e01Panel : public Panel {
 public:
  const char* kind() const override { return "gdeb0709e01"; }
  PanelDims dims() const override { return PanelDims{1200, 1600}; }
  bool begin() override;
  bool supportsPartial() const override { return false; }
  bool drawPacked4bpp(const uint8_t* buf, size_t len) override;
  bool drawDeviceStatus(PanelStatusIcon icon, const char* title,
                        const char* detail, const char* footer = nullptr,
                        uint8_t progress = 0,
                        bool showProgress = false) override;
  bool drawStatus(const char* title, const char* lines[], int numLines,
                  bool setupHeader = true) override;
  bool drawSetupQR(const char* title, const char* apName, const char* url) override;
  bool drawPairing(const char* claimCode, const char* where) override;
  void sleep() override;

 private:
  void drawQRCode(const char* text, int x, int y, int size);
};
