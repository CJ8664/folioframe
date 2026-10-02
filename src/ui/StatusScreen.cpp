#include "StatusScreen.h"

void StatusScreen::showPortal(const char* apName, const char* url) {
  const char* lines[] = {
      "1. Join Wi-Fi network:", apName,
      "2. Open this address:", url,
      "3. Enter your Wi-Fi details", "",
      "Press BTN1 to exit setup.",
  };
  panel_->drawStatus("SpectraFrame setup", lines, 6);
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
