#pragma once
// Sleep scheduling: clock-aligned refresh intervals with quiet-hours
// sleep-through. Pure logic — time is passed in, never read here.
#include <cstdint>

namespace spectra {

struct SleepPlan {
  uint32_t sleepSeconds;  // how long to deep-sleep
  bool skippedForQuiet;   // true if the refresh was deferred past quiet hours
};

// nowEpoch: current UTC epoch seconds. intervalSec: refresh cadence.
// quietStartMin/quietEndMin: local-time window (start==end disables).
// tzOffsetMin: local = UTC + offset (no DST handling here; POSIX TZ string
// in TimeSync handles DST, this takes the already-resolved offset).
// minSleepSec / maxSleepSec: safety clamps.
// clockOk: false when the clock is unsynced (NTP failed). The quiet-window
// extension is skipped, since wall-clock math on garbage time is meaningless.
SleepPlan computeSleep(uint32_t nowEpoch, uint32_t intervalSec,
                       int quietStartMin, int quietEndMin, int tzOffsetMin,
                       uint32_t minSleepSec = 60,
                       uint32_t maxSleepSec = 7 * 24 * 3600,
                       bool clockOk = true);

}  // namespace spectra
