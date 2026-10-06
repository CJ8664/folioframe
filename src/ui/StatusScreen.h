#pragma once
// On-panel text screens: onboarding, portal, errors, OTA, battery/Wi-Fi
// workflows. Rendered through the Panel seam so they work on any panel.
//
// Copy style: friendly plain language, every screen names a clear next
// step. No jargon, no dead ends.
#include <stdint.h>

#include "../hal/Panel.h"

class StatusScreen {
 public:
  explicit StatusScreen(Panel* panel) : panel_(panel) {}

  void showPortal(const char* apName, const char* url);
  void showSettings(const char* url);
  void showPairing(const char* claimCode, const char* where);
  void showPaired();
  void showError(const char* title, const char* detail);

  // --- OTA flow ---
  void showOtaChecking();
  void showOtaUpToDate();
  // versionLabel: "v0.0.3 (build 20)" or "build 20" when no version string.
  void showOtaAvailable(const char* versionLabel);
  // Manual mode: an update was staged on an earlier wake.
  void showUpdatePrompt(const char* versionLabel);
  void showOtaProgress(uint8_t pct);
  void showOtaVerifying();
  void showOtaDone();
  void showOtaFailed(const char* reason);
  void showOtaBatteryLow();

  // --- Error workflows ---
  void showLowBattery(uint8_t pct);   // warn, then continue normally
  void showCriticalBattery();        // too low for radio; sleeping
  void showWiFiLost();               // connect failed
  void showWiFiWeak(int rssiDbm);    // connected but poor signal
  void showRenderError(const char* detail);  // photo fetched but bad paint

 private:
  Panel* panel_;
};
