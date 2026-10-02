#include "framework.h"
#include "../src/core/Validate.h"

using namespace spectra;

TEST(name_validation) {
  EXPECT_TRUE(validDeviceName("spectraframe"));
  EXPECT_TRUE(validDeviceName("sf-a1b2c3"));
  EXPECT_TRUE(validDeviceName("a"));
  EXPECT_FALSE(validDeviceName(""));
  EXPECT_FALSE(validDeviceName("-abc"));
  EXPECT_FALSE(validDeviceName("abc-"));
  EXPECT_FALSE(validDeviceName("Abc"));
  EXPECT_FALSE(validDeviceName("a b"));
  EXPECT_FALSE(validDeviceName(std::string(25, 'a')));
  EXPECT_TRUE(validDeviceName(std::string(24, 'a')));
}

TEST(interval_validation) {
  EXPECT_TRUE(validIntervalMinutes(15));
  EXPECT_TRUE(validIntervalMinutes(60));
  EXPECT_TRUE(validIntervalMinutes(1440));
  EXPECT_FALSE(validIntervalMinutes(0));
  EXPECT_FALSE(validIntervalMinutes(45));
  EXPECT_FALSE(validIntervalMinutes(100));
}

TEST(timezone_validation) {
  EXPECT_TRUE(validTimezone("auto"));
  EXPECT_TRUE(validTimezone("PST8PDT,M3.2.0,M11.1.0"));
  EXPECT_TRUE(validTimezone("UTC0"));
  EXPECT_FALSE(validTimezone(""));
  EXPECT_FALSE(validTimezone("a b"));
  EXPECT_FALSE(validTimezone(std::string(65, 'x')));
}

int main() { return runAllTests(); }
