#include "../src/core/JsonLite.h"

#include "framework.h"

using spectra::jsonOk;
using spectra::jsonString;

TEST(jsonlite_basic) {
  std::string b = "{\"ok\":true,\"claim_code\":\"AB12-CD34\",\"expires_in\":600}";
  EXPECT_TRUE(jsonOk(b));
  EXPECT_TRUE(jsonString(b, "claim_code") == "AB12-CD34");
  EXPECT_TRUE(jsonString(b, "missing") == "");
  EXPECT_TRUE(jsonString(b, "ok") == "");  // not a string
}

TEST(jsonlite_whitespace) {
  std::string b = "{ \"ok\" : true , \"status\" : \"pending\" }";
  EXPECT_TRUE(jsonOk(b));
  EXPECT_TRUE(jsonString(b, "status") == "pending");
}

TEST(jsonlite_ok_false) {
  EXPECT_FALSE(jsonOk("{\"ok\":false}"));
  EXPECT_FALSE(jsonOk("{\"ok\":1}"));
  EXPECT_FALSE(jsonOk("{}"));
  EXPECT_FALSE(jsonOk("not json"));
}

TEST(jsonlite_escapes) {
  std::string b = "{\"device_token\":\"ab\\\\cd\\\"ef\"}";
  EXPECT_TRUE(jsonString(b, "device_token") == "ab\\cd\"ef");
}

TEST(jsonlite_unterminated) {
  EXPECT_TRUE(jsonString("{\"k\":\"abc", "k") == "");
  EXPECT_TRUE(jsonString("{\"k\":", "k") == "");
}

TEST(jsonlite_claimed_shape) {
  std::string b =
      "{\"ok\":true,\"status\":\"claimed\",\"device_token\":\"tok123\","
      "\"device_id\":\"sf-abcdef012345\"}";
  EXPECT_TRUE(jsonOk(b));
  EXPECT_TRUE(jsonString(b, "status") == "claimed");
  EXPECT_TRUE(jsonString(b, "device_token") == "tok123");
}

int main() { return runAllTests(); }
