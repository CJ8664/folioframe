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
  panel_->drawPairing(claimCode, where);
}

void StatusScreen::showPaired() {
  const char* lines[] = {"Paired!", "", "Fetching first image..."};
  panel_->drawStatus("FolioFrame", lines, 3, false);
}

void StatusScreen::showError(const char* title, const char* detail) {
  const char* lines[] = {detail, "", "Will retry on next wake."};
  panel_->drawStatus(title, lines, 3, false);
}

// --- OTA flow ---

void StatusScreen::showOtaChecking() {
  panel_->drawDeviceStatus(PanelStatusIcon::Checking, "Checking for update...",
                           "This takes a moment.");
}

void StatusScreen::showOtaUpToDate() {
  const char* lines[] = {"You're up to date.", "", "Going back to sleep."};
  panel_->drawStatus("Software update", lines, 3, false);
}

void StatusScreen::showOtaNoChannel() {
  const char* lines[] = {"No update channel is published.",
                         "Keeping the current software."};
  panel_->drawStatus("Software update", lines, 2, false);
}

void StatusScreen::showOtaAvailable(const char* versionLabel) {
  char detail[96];
  snprintf(detail, sizeof(detail), "Version %.56s is ready to install.",
           versionLabel ? versionLabel : "update");
  panel_->drawDeviceStatus(PanelStatusIcon::Download, "Update available",
                           detail, "KEY2: Install now   KEY1: Skip for now");
}

void StatusScreen::showUpdatePrompt(const char* versionLabel) {
  showOtaAvailable(versionLabel);
}

void StatusScreen::showOtaProgress(uint8_t pct) {
  panel_->drawDeviceStatus(PanelStatusIcon::Download, "Downloading update...",
                           "Keep the frame powered on.", nullptr, pct, true);
}

void StatusScreen::showOtaVerifying() {
  panel_->drawDeviceStatus(PanelStatusIcon::Verifying, "Verifying update...",
                           "Making sure the download arrived complete and correct.");
}

void StatusScreen::showOtaDone() {
  panel_->drawDeviceStatus(PanelStatusIcon::Success, "Update complete.",
                           "Restarting with the new version...");
}

void StatusScreen::showOtaFailed(const char* reason) {
  char footer[96];
  if (reason && reason[0]) {
    snprintf(footer, sizeof(footer), "Details: %.80s", reason);
  } else {
    footer[0] = '\0';
  }
  panel_->drawDeviceStatus(
      PanelStatusIcon::Failure, "The update didn't install.",
      "Keeping your current version -- the frame will try again later.",
      footer[0] ? footer : nullptr);
}

void StatusScreen::showOtaBatteryLow() {
  panel_->drawDeviceStatus(PanelStatusIcon::CriticalBattery,
                           "Battery too low to update.",
                           "Plug in USB to charge, then try again.");
}

// --- Error workflows ---

void StatusScreen::showLowBattery(uint8_t pct) {
  char detail[96];
  snprintf(detail, sizeof(detail),
           "%u%% battery left. Showing photos as usual -- please charge soon.",
           pct);
  panel_->drawDeviceStatus(PanelStatusIcon::Battery, "Battery low.", detail);
}

void StatusScreen::showCriticalBattery() {
  panel_->drawDeviceStatus(
      PanelStatusIcon::CriticalBattery, "Battery critically low.",
      "Connect USB power. Skipping Wi-Fi and going to sleep to save power.");
}

void StatusScreen::showWiFiLost() {
  panel_->drawDeviceStatus(PanelStatusIcon::WifiLost, "Wi-Fi connection lost.",
                           "Press KEY1 to open settings. We'll retry Wi-Fi later.");
}

void StatusScreen::showWiFiWeak(int rssiDbm) {
  (void)rssiDbm;
  panel_->drawDeviceStatus(
      PanelStatusIcon::WifiWeak, "Wi-Fi signal is weak.",
      "Move the frame closer to your router if new photos take longer to arrive.");
}

void StatusScreen::showRenderError(const char* detail) {
  panel_->drawDeviceStatus(
      PanelStatusIcon::PhotoError, "This photo didn't load.",
      "Keeping the last photo -- we'll try again on the next wake.",
      detail && detail[0] ? detail : nullptr);
}
