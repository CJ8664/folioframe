#pragma once
// Minimal zero-dependency test harness.
#include <cstdio>
#include <functional>
#include <string>
#include <vector>

namespace t {
struct Case {
  const char* name;
  std::function<void()> fn;
};
inline std::vector<Case>& registry() {
  static std::vector<Case> r;
  return r;
}
inline int failures = 0;
struct Registrar {
  Registrar(const char* n, std::function<void()> f) {
    registry().push_back({n, f});
  }
};
}  // namespace t

#define TEST(name)                                             \
  static void test_body_##name();                              \
  static t::Registrar test_reg_##name(#name, test_body_##name); \
  static void test_body_##name()

#define EXPECT_TRUE(cond)                                                  \
  do {                                                                     \
    if (!(cond)) {                                                         \
      std::printf("  FAIL %s:%d: expected true: %s\n", __FILE__, __LINE__,   \
                  #cond);                                                  \
      t::failures++;                                                       \
    }                                                                      \
  } while (0)

#define EXPECT_FALSE(cond) EXPECT_TRUE(!(cond))

#define EXPECT_EQ(a, b)                                                    \
  do {                                                                     \
    auto va = (a);                                                         \
    auto vb = (b);                                                         \
    if (!(va == vb)) {                                                     \
      std::printf("  FAIL %s:%d: %s != %s\n", __FILE__, __LINE__, #a, #b);  \
      t::failures++;                                                       \
    }                                                                      \
  } while (0)

inline int runAllTests() {
  int passed = 0;
  for (auto& c : t::registry()) {
    int before = t::failures;
    c.fn();
    if (t::failures == before) {
      passed++;
    } else {
      std::printf("FAILED: %s\n", c.name);
    }
  }
  std::printf("%d/%d tests passed\n", passed, (int)t::registry().size());
  return t::failures == 0 ? 0 : 1;
}
