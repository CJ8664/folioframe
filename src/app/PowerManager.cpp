#include "PowerManager.h"

#include "../../include/board_config.h"

int PowerManager::localMinutesNow() {
  time_t now = time(nullptr);
  struct tm tmv;
  localtime_r(&now, &tmv);
  return tmv.tm_hour * 60 + tmv.tm_min;
}

bool PowerManager::inQuietNow(const Settings& s, int32_t utcOffsetMin) {
  (void)utcOffsetMin;  // localtime already applies TZ
  if (!s.quietEnabled) return false;
  return spectra::inQuietWindow(localMinutesNow(), s.quietStartMin,
                                s.quietEndMin);
}

void PowerManager::sleepUntilNext(const Settings& s, int32_t utcOffsetMin) {
  time_t now = time(nullptr);
  spectra::SleepPlan plan = spectra::computeSleep(
      (uint32_t)now, s.intervalMinutes * 60,
      s.quietEnabled ? s.quietStartMin : 0,
      s.quietEnabled ? s.quietEndMin : 0, (int)utcOffsetMin,
      EE02_MIN_SLEEP_SEC, EE02_MAX_SLEEP_SEC);
  board_->enableButtonWakeup();
  board_->deepSleep((uint64_t)plan.sleepSeconds * 1000000ULL);
}
