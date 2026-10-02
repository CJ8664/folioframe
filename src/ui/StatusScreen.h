#pragma once
// On-panel text screens: onboarding, portal, errors. Rendered through the
// Panel seam so they work on any panel.
#include "../hal/Panel.h"

class StatusScreen {
 public:
  explicit StatusScreen(Panel* panel) : panel_(panel) {}

  void showPortal(const char* apName, const char* url);
  void showError(const char* title, const char* detail);
  void showFetching();
  void showOk();

 private:
  Panel* panel_;
};
