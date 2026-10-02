#include <ctime>

#include "framework.h"
#include "../src/core/Scheduler.h"

using namespace spectra;

// Build a UTC epoch for assertions.
static uint32_t utc(int y, int mo, int d, int h, int mi) {
  struct tm t = {};
  t.tm_year = y - 1900;
  t.tm_mon = mo - 1;
  t.tm_mday = d;
  t.tm_hour = h;
  t.tm_min = mi;
  return (uint32_t)timegm(&t);
}

TEST(sched_no_quiet_simple) {
  SleepPlan p = computeSleep(utc(2026, 10, 2, 12, 0), 3600, 0, 0, 0);
  EXPECT_EQ(p.sleepSeconds, 3600u);
  EXPECT_FALSE(p.skippedForQuiet);
}

TEST(sched_min_clamp) {
  SleepPlan p = computeSleep(utc(2026, 10, 2, 12, 0), 10, 0, 0, 0);
  EXPECT_EQ(p.sleepSeconds, 60u);
}

TEST(sched_max_clamp) {
  SleepPlan p = computeSleep(utc(2026, 10, 2, 12, 0), 30 * 24 * 3600, 0, 0, 0);
  EXPECT_EQ(p.sleepSeconds, (uint32_t)7 * 24 * 3600);
}

TEST(sched_quiet_sleep_through) {
  // Now 21:30 UTC, interval 1h -> wake 22:30 lands in quiet 22:00-07:00.
  // Sleep = 3600 + (07:00 - 22:30) = 3600 + 30600 = 34200.
  SleepPlan p =
      computeSleep(utc(2026, 10, 2, 21, 30), 3600, 1320, 420, 0);
  EXPECT_TRUE(p.skippedForQuiet);
  EXPECT_EQ(p.sleepSeconds, 34200u);
}

TEST(sched_quiet_not_triggered) {
  // Now 12:00 UTC, interval 1h -> wake 13:00, outside quiet 22:00-07:00.
  SleepPlan p =
      computeSleep(utc(2026, 10, 2, 12, 0), 3600, 1320, 420, 0);
  EXPECT_FALSE(p.skippedForQuiet);
  EXPECT_EQ(p.sleepSeconds, 3600u);
}

TEST(sched_tz_offset_applies) {
  // Device at UTC+2: 19:30 UTC = 21:30 local; wake 22:30 local is in quiet.
  SleepPlan p =
      computeSleep(utc(2026, 10, 2, 19, 30), 3600, 1320, 420, 120);
  EXPECT_TRUE(p.skippedForQuiet);
}

int main() { return runAllTests(); }
