#include "Scheduler.h"

#include "QuietHours.h"

namespace spectra {

SleepPlan computeSleep(uint32_t nowEpoch, uint32_t intervalSec,
                       int quietStartMin, int quietEndMin, int tzOffsetMin,
                       uint32_t minSleepSec, uint32_t maxSleepSec) {
  SleepPlan plan{intervalSec, false};
  if (plan.sleepSeconds < minSleepSec) plan.sleepSeconds = minSleepSec;
  if (plan.sleepSeconds > maxSleepSec) plan.sleepSeconds = maxSleepSec;

  // Where would the next refresh land, in local minutes?
  uint32_t wakeEpoch = nowEpoch + plan.sleepSeconds;
  int64_t localSec = (int64_t)wakeEpoch + (int64_t)tzOffsetMin * 60;
  int wakeMin = (int)((localSec / 60) % (24 * 60));
  if (wakeMin < 0) wakeMin += 24 * 60;

  if (inQuietWindow(wakeMin, quietStartMin, quietEndMin)) {
    // Sleep straight through to the end of the quiet window.
    uint32_t toEnd = secondsToWindowEnd(wakeMin, quietEndMin);
    plan.sleepSeconds += toEnd;
    plan.skippedForQuiet = true;
    if (plan.sleepSeconds > maxSleepSec) plan.sleepSeconds = maxSleepSec;
  }
  return plan;
}

}  // namespace spectra
