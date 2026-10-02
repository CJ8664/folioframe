#pragma once
// Power policy: compute sleep via core::Scheduler, arm button wakeup,
// cut the panel rail, and deep-sleep. Also the "quiet hours" skip-fetch.
#include <Arduino.h>

#include "../core/QuietHours.h"
#include "../core/Scheduler.h"
#include "../hal/Board.h"
#include "Config.h"

class PowerManager {
 public:
  explicit PowerManager(Board* board) : board_(board) {}

  // True when we woke inside the quiet window → skip fetching, sleep through.
  bool inQuietNow(const Settings& s, int32_t utcOffsetMin);

  // Compute the sleep plan and enter deep sleep (does not return).
  void sleepUntilNext(const Settings& s, int32_t utcOffsetMin);

 private:
  Board* board_;
  static int localMinutesNow();
};
