#include "framework.h"
#include "../src/core/OtaManifest.h"

using namespace spectra;

TEST(manifest_valid) {
  OtaManifest m;
  EXPECT_TRUE(parseOtaManifest("build=42\nmd5=abcdef0123456789abcdef0123456789",
                               m));
  EXPECT_EQ(m.build, 42u);
  EXPECT_TRUE(m.hasMd5);
  EXPECT_EQ(m.md5, "abcdef0123456789abcdef0123456789");
}

TEST(manifest_no_md5_ok) {
  OtaManifest m;
  EXPECT_TRUE(parseOtaManifest("build=7\n", m));
  EXPECT_EQ(m.build, 7u);
  EXPECT_FALSE(m.hasMd5);
}

TEST(manifest_rejects) {
  OtaManifest m;
  EXPECT_FALSE(parseOtaManifest("md5=abcdef0123456789abcdef0123456789", m));
  EXPECT_FALSE(parseOtaManifest("build=0\n", m));
  EXPECT_FALSE(parseOtaManifest("build=abc\n", m));
  EXPECT_FALSE(
      parseOtaManifest("build=42\nmd5=ABCDEF0123456789ABCDEF0123456789", m));
  EXPECT_FALSE(parseOtaManifest("build=42\nmd5=tooshort", m));
  EXPECT_FALSE(parseOtaManifest("build=42\nunknown=1\n", m));
  EXPECT_FALSE(parseOtaManifest("notakeyvalue\n", m));
  EXPECT_FALSE(parseOtaManifest("", m));
}

TEST(manifest_ordering) {
  OtaManifest m;
  parseOtaManifest("build=42\n", m);
  EXPECT_TRUE(shouldUpdate(41, m));
  EXPECT_FALSE(shouldUpdate(42, m));
  EXPECT_FALSE(shouldUpdate(43, m));
}

TEST(md5_validation) {
  EXPECT_TRUE(validMd5("abcdef0123456789abcdef0123456789"));
  EXPECT_FALSE(validMd5("abcdef0123456789ABCDEF0123456789"));
  EXPECT_FALSE(validMd5("abc"));
  EXPECT_FALSE(validMd5(""));
}

int main() { return runAllTests(); }
