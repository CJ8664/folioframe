#include "StatusScreen.h"

void StatusScreen::showPortal(const char* apName, const char* url) {
  panel_->drawSetupQR("SpectraFrame Setup", apName, url);
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
      "1. Open your SpectraFrame", "   console in a browser",
      "2. Go to 'Pair a frame'",  "3. Enter this code:",
      claimCode, "", where,
  };
  panel_->drawStatus("Pair this frame", lines, 7);
}

void StatusScreen::showPaired() {
  const char* lines[] = {"Paired!", "", "Fetching first image..."};
  panel_->drawStatus("SpectraFrame", lines, 3);
}

void StatusScreen::showError(const char* title, const char* detail) {
  const char* lines[] = {detail, "", "Will retry on next wake."};
  panel_->drawStatus(title, lines, 3);
}

void StatusScreen::showFetching() {
  const char* lines[] = {"Fetching new image..."};
  panel_->drawStatus("SpectraFrame", lines, 1);
}

void StatusScreen::showOk() {
  const char* lines[] = {"Up to date.", "", "Going to sleep."};
  panel_->drawStatus("SpectraFrame", lines, 3);
}
