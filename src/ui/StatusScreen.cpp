#include "StatusScreen.h"

#include <stdio.h>

void StatusScreen::showPortal(const char* apName, const char* url) {
  panel_->drawSetupQR("FolioFrame Setup", apName, url);
}

void StatusScreen::showSettings(const char* url) {
  // The frame is on the home Wi-Fi; the settings page lives at its LAN IP.
  const char* lines[] = {
      "On your phone or computer,", "open this address:",
      url, "", "to configure this frame.",
  };
  panel_->drawStatus("Frame settings", lines, 5);
}

void StatusScreen::showPairing(const char* claimCode, const char* where) {
  const char* lines[] = {
      "1. Open your FolioFrame", "   console in a browser",
      "2. Go to 'Pair a frame'",  "3. Enter this code:",
      claimCode, "", where,
  };
  panel_->drawStatus("Pair this frame", lines, 7);
}

void StatusScreen::showPaired() {
  const char* lines[] = {"Paired!", "", "Fetching first image..."};
  panel_->drawStatus("FolioFrame", lines, 3);
}

void StatusScreen::showError(const char* title, const char* detail) {
  const char* lines[] = {detail, "", "Will retry on next wake."};
  panel_->drawStatus(title, lines, 3);
}

// --- OTA flow ---

void StatusScreen::showOtaChecking() {
  const char* lines[] = {"Checking for update...", "", "This takes a moment."};
  panel_->drawStatus("Software update", lines, 3);
}

void StatusScreen::showOtaUpToDate() {
  const char* lines[] = {"You're up to date.", "", "Going back to sleep."};
  panel_->drawStatus("Software update", lines, 3);
}

void StatusScreen::showOtaAvailable(const char* versionLabel) {
  char first[64];
  snprintf(first, sizeof(first), "Firmware %s is ready.", versionLabel);
  const char* lines[] = {first, "", "Press KEY2 to install,",
                         "KEY1 to skip."};
  panel_->drawStatus("Update available", lines, 4);
}

void StatusScreen::showUpdatePrompt(const char* versionLabel) {
  char first[64];
  snprintf(first, sizeof(first), "Firmware %s is ready.", versionLabel);
  const char* lines[] = {first, "", "Hold KEY2 to install now,",
                         "KEY1 to dismiss."};
  panel_->drawStatus("Update ready", lines, 4);
}

void StatusScreen::showOtaProgress(uint8_t pct) {
  // Text progress bar: a full e-paper refresh takes ~30 s, so callers
  // update this at coarse steps only.
  char bar[40];
  const int kWidth = 20;
  int filled = (pct * kWidth) / 100;
  if (filled > kWidth) filled = kWidth;
  int i = 0;
  bar[i++] = '[';
  for (int b = 0; b < kWidth; b++) bar[i++] = (b < filled) ? '=' : ' ';
  bar[i++] = ']';
  bar[i++] = ' ';
  snprintf(bar + i, sizeof(bar) - i, "%u%%", pct);
  const char* lines[] = {"Downloading update...", bar, "",
                         "Keep the frame powered."};
  panel_->drawStatus("Updating...", lines, 4);
}

void StatusScreen::showOtaVerifying() {
  const char* lines[] = {"Verifying update...", "", "Almost there."};
  panel_->drawStatus("Updating...", lines, 3);
}

void StatusScreen::showOtaDone() {
  const char* lines[] = {"Restarting with the", "new software..."};
  panel_->drawStatus("Update complete", lines, 2);
}

void StatusScreen::showOtaFailed(const char* reason) {
  const char* lines[] = {reason, "", "Keeping the current version.",
                         "Will try again on next wake."};
  panel_->drawStatus("Update didn't work", lines, 4);
}

void StatusScreen::showOtaBatteryLow() {
  const char* lines[] = {"Battery is too low to", "install safely.", "",
                         "Plug in USB and try again."};
  panel_->drawStatus("Update paused", lines, 4);
}

// --- Error workflows ---

void StatusScreen::showLowBattery(uint8_t pct) {
  char first[48];
  snprintf(first, sizeof(first), "Battery is at %u%%.", pct);
  const char* lines[] = {first, "The frame keeps working,",
                         "but please charge it soon."};
  panel_->drawStatus("Battery low", lines, 3);
}

void StatusScreen::showCriticalBattery() {
  const char* lines[] = {"Going to sleep to", "protect the battery.", "",
                         "Please plug in USB."};
  panel_->drawStatus("Battery very low", lines, 4);
}

void StatusScreen::showWiFiLost() {
  const char* lines[] = {
      "Couldn't connect to Wi-Fi.", "",
      "Hold KEY1 for settings to", "check the Wi-Fi details.",
      "Will retry on next wake.",
  };
  panel_->drawStatus("No Wi-Fi", lines, 5);
}

void StatusScreen::showWiFiWeak(int rssiDbm) {
  char first[48];
  snprintf(first, sizeof(first), "Signal is weak (%d dBm).", rssiDbm);
  const char* lines[] = {first, "Trying anyway --", "moving the frame closer",
                         "to the router helps."};
  panel_->drawStatus("Weak Wi-Fi", lines, 4);
}

void StatusScreen::showRenderError(const char* detail) {
  const char* lines[] = {detail, "", "Keeping the last good photo.",
                         "Will retry on next wake."};
  panel_->drawStatus("Photo didn't load right", lines, 4);
}
