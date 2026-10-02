#include "framework.h"
#include "../src/core/BatteryCurve.h"

using namespace spectra;

TEST(battery_clamps) {
  EXPECT_EQ(batteryPercent(0), 0u);
  EXPECT_EQ(batteryPercent(3300), 0u);
  EXPECT_EQ(batteryPercent(3400), 0u);
  EXPECT_EQ(batteryPercent(4200), 100u);
  EXPECT_EQ(batteryPercent(4400), 100u);
}

TEST(battery_curve_points) {
  EXPECT_EQ(batteryPercent(3700), 25u);
  EXPECT_EQ(batteryPercent(3750), 35u);
  EXPECT_EQ(batteryPercent(4000), 78u);
  EXPECT_EQ(batteryPercent(4100), 90u);
}

TEST(battery_interpolation) {
  EXPECT_EQ(batteryPercent(3725), 30u);  // midpoint of 25..35
  EXPECT_EQ(batteryPercent(3650), 15u);
  uint8_t lo = batteryPercent(3800);  // 45
  uint8_t hi = batteryPercent(3850);  // 55
  uint8_t mid = batteryPercent(3825);
  EXPECT_TRUE(mid > lo && mid < hi);
}

int main() { return runAllTests(); }
