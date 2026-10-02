#include "framework.h"
#include "../src/core/UrlTemplate.h"

using namespace spectra;

TEST(url_passthrough) {
  UrlTokens t{123, 1200, 1600};
  EXPECT_EQ(expandUrlTemplate("https://example.com/a.png", t),
            "https://example.com/a.png");
}

TEST(url_all_tokens) {
  UrlTokens t{42, 1200, 1600};
  EXPECT_EQ(
      expandUrlTemplate("https://picsum.photos/seed/{seed}/{width}/{height}",
                        t),
      "https://picsum.photos/seed/42/1200/1600");
}

TEST(url_repeated_token) {
  UrlTokens t{7, 800, 600};
  EXPECT_EQ(expandUrlTemplate("{seed}-{seed}", t), "7-7");
}

TEST(url_validation) {
  EXPECT_TRUE(validImageUrl("http://a/b"));
  EXPECT_TRUE(validImageUrl("https://a/b"));
  EXPECT_FALSE(validImageUrl(""));
  EXPECT_FALSE(validImageUrl("ftp://a/b"));
  EXPECT_FALSE(validImageUrl("example.com/a.png"));
  EXPECT_FALSE(validImageUrl(std::string(513, 'x')));
  EXPECT_TRUE(validImageUrl(std::string("https://") + std::string(504, 'x')));
}

int main() { return runAllTests(); }
