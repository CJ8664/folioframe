#include "../src/core/JsonLite.h"

#include "framework.h"

using spectra::jsonBool;
using spectra::jsonInt;
using spectra::jsonNestedBool;
using spectra::jsonNestedInt;
using spectra::jsonNestedString;
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

TEST(jsonlite_nested_bool) {
  std::string b = "{\"ok\":true,\"settings\":{\"auto_update\":false}}";
  EXPECT_FALSE(jsonNestedBool(b, "settings", "auto_update", true));
  b = "{\"ok\":true,\"settings\":{\"auto_update\":true}}";
  EXPECT_TRUE(jsonNestedBool(b, "settings", "auto_update", false));
  // Missing settings object -> default.
  EXPECT_TRUE(jsonNestedBool("{\"ok\":true}", "settings", "auto_update", true));
  // Missing key inside settings -> default.
  b = "{\"ok\":true,\"settings\":{}}";
  EXPECT_FALSE(jsonNestedBool(b, "settings", "auto_update", false));
  // Key present but not a bool -> default.
  b = "{\"ok\":true,\"settings\":{\"auto_update\":\"yes\"}}";
  EXPECT_TRUE(jsonNestedBool(b, "settings", "auto_update", true));
}

TEST(jsonlite_bool) {
  EXPECT_TRUE(jsonBool("{\"a\":true}", "a", false));
  EXPECT_FALSE(jsonBool("{\"a\":false}", "a", true));
  EXPECT_TRUE(jsonBool("{ \"a\" : true }", "a", false));  // whitespace
  EXPECT_TRUE(jsonBool("{\"a\":true }", "a", false));     // trailing space
  // Missing key -> default.
  EXPECT_TRUE(jsonBool("{}", "a", true));
  EXPECT_FALSE(jsonBool("{}", "a", false));
  // Present but not a bool -> default.
  EXPECT_TRUE(jsonBool("{\"a\":1}", "a", true));
  EXPECT_TRUE(jsonBool("{\"a\":\"true\"}", "a", true));
  EXPECT_TRUE(jsonBool("{\"a\":nul}", "a", true));
}

TEST(jsonlite_int) {
  EXPECT_TRUE(jsonInt("{\"a\":60}", "a", 0) == 60);
  EXPECT_TRUE(jsonInt("{\"a\":-5}", "a", 0) == -5);
  EXPECT_TRUE(jsonInt("{ \"a\" : 1440 }", "a", 0) == 1440);  // whitespace
  EXPECT_TRUE(jsonInt("{\"a\":0}", "a", 7) == 0);
  // Missing key -> default.
  EXPECT_TRUE(jsonInt("{}", "a", 7) == 7);
  // Present but not an int -> default.
  EXPECT_TRUE(jsonInt("{\"a\":\"60\"}", "a", 7) == 7);
  EXPECT_TRUE(jsonInt("{\"a\":true}", "a", 7) == 7);
  EXPECT_TRUE(jsonInt("{\"a\":6.5}", "a", 7) == 7);
  EXPECT_TRUE(jsonInt("{\"a\":}", "a", 7) == 7);
}

TEST(jsonlite_nested_int_string) {
  std::string b =
      "{\"ok\":true,\"settings\":{\"interval_minutes\":60,\"quiet_enabled\":"
      "true,\"timezone\":\"America/New_York\",\"orientation\":2}}";
  EXPECT_TRUE(jsonNestedInt(b, "settings", "interval_minutes", 0) == 60);
  EXPECT_TRUE(jsonNestedBool(b, "settings", "quiet_enabled", false));
  EXPECT_TRUE(jsonNestedString(b, "settings", "timezone") == "America/New_York");
  EXPECT_TRUE(jsonNestedInt(b, "settings", "orientation", 0) == 2);
  // Missing keys -> defaults; missing object -> defaults.
  EXPECT_TRUE(jsonNestedInt(b, "settings", "nope", 9) == 9);
  EXPECT_TRUE(jsonNestedString(b, "settings", "nope") == "");
  EXPECT_TRUE(jsonNestedInt("{}", "settings", "interval_minutes", 9) == 9);
  EXPECT_TRUE(jsonNestedString("{}", "settings", "timezone") == "");
}

int main() { return runAllTests(); }
