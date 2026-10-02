#include "framework.h"
#include "../src/core/QuietHours.h"

using namespace spectra;

TEST(quiet_disabled_when_start_eq_end) {
  EXPECT_FALSE(inQuietWindow(0, 600, 600));
  EXPECT_FALSE(inQuietWindow(720, 0, 0));
}

TEST(quiet_simple_window) {
  // 09:00 - 17:00
  EXPECT_TRUE(inQuietWindow(720, 540, 1020));
  EXPECT_FALSE(inQuietWindow(539, 540, 1020));
  EXPECT_TRUE(inQuietWindow(1019, 540, 1020));
  EXPECT_FALSE(inQuietWindow(1020, 540, 1020));  // end exclusive
  EXPECT_FALSE(inQuietWindow(0, 540, 1020));
}

TEST(quiet_wraps_midnight) {
  // 22:00 - 07:00
  EXPECT_TRUE(inQuietWindow(1410, 1320, 420));   // 23:30
  EXPECT_TRUE(inQuietWindow(0, 1320, 420));      // 00:00
  EXPECT_TRUE(inQuietWindow(419, 1320, 420));    // 06:59
  EXPECT_FALSE(inQuietWindow(420, 1320, 420));   // 07:00
  EXPECT_FALSE(inQuietWindow(1319, 1320, 420));  // 21:59
  EXPECT_FALSE(inQuietWindow(720, 1320, 420));   // noon
}

TEST(quiet_seconds_to_end) {
  EXPECT_EQ(secondsToWindowEnd(1410, 420), 27000u);  // 23:30 -> 07:00
  EXPECT_EQ(secondsToWindowEnd(360, 420), 3600u);    // 06:00 -> 07:00
  EXPECT_EQ(secondsToWindowEnd(1019, 1020), 60u);    // 1 min left
}

int main() { return runAllTests(); }
