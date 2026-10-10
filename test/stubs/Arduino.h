#pragma once
// Minimal Arduino API stubs — ONLY for host syntax-checking (Level 2).
// They mirror the signatures used by src/, not the real implementations.
#include <cstdarg>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>

#define HIGH 1
#define LOW 0
#define INPUT 0
#define OUTPUT 1
#define INPUT_PULLUP 2
#define FALLING 3
#define HEX 16
#define RTC_DATA_ATTR
#define IRAM_ATTR
void attachInterruptArg(int, void (*)(void*), void*, int);

class String {
  std::string s_;

 public:
  String() = default;
  String(const char* s) : s_(s ? s : "") {}
  String(const std::string& s) : s_(s) {}
  String(int v) : s_(std::to_string(v)) {}
  String(unsigned int v) : s_(std::to_string(v)) {}
  String(uint16_t v) : s_(std::to_string(v)) {}
  String(long v) : s_(std::to_string(v)) {}
  String(unsigned long v) : s_(std::to_string(v)) {}
  String(unsigned long v, int) : s_(std::to_string(v)) {}  // base ignored
  const char* c_str() const { return s_.c_str(); }
  unsigned int length() const { return (unsigned int)s_.size(); }
  bool isEmpty() const { return s_.empty(); }
  bool endsWith(const char* p) const {
    size_t n = std::strlen(p);
    return s_.size() >= n && s_.compare(s_.size() - n, n, p) == 0;
  }
  void remove(unsigned int i, unsigned int n = (unsigned int)-1) {
    s_.erase(i, n == (unsigned int)-1 ? std::string::npos : n);
  }
  void trim() {
    size_t a = s_.find_first_not_of(" \t\n\r");
    if (a == std::string::npos) {
      s_.clear();
      return;
    }
    s_ = s_.substr(a, s_.find_last_not_of(" \t\n\r") - a + 1);
  }
  int indexOf(const char* p) const {
    auto i = s_.find(p);
    return i == std::string::npos ? -1 : (int)i;
  }
  int indexOf(char c, unsigned int from = 0) const {
    auto i = s_.find(c, from);
    return i == std::string::npos ? -1 : (int)i;
  }
  int indexOf(const char* p, unsigned int from) const {
    auto i = s_.find(p, from);
    return i == std::string::npos ? -1 : (int)i;
  }
  bool startsWith(const char* p) const { return s_.rfind(p, 0) == 0; }
  int toInt() const { return std::atoi(s_.c_str()); }
  String substring(int from, int to = -1) const {
    return to < 0 ? String(s_.substr(from)) : String(s_.substr(from, to - from));
  }
  String& operator+=(const String& o) {
    s_ += o.s_;
    return *this;
  }
  String& operator+=(const char* o) {
    s_ += o;
    return *this;
  }
  bool operator==(const char* o) const { return s_ == o; }
  bool operator==(const String& o) const { return s_ == o.s_; }
  bool operator!=(const char* o) const { return s_ != o; }
  bool operator!=(const String& o) const { return s_ != o.s_; }
  char operator[](unsigned int i) const { return i < s_.size() ? s_[i] : '\0'; }
  friend String operator+(const String& a, const String& b) {
    return String(a.s_ + b.s_);
  }
  friend String operator+(const String& a, const char* b) {
    return String(a.s_ + b);
  }
  friend String operator+(const char* a, const String& b) {
    return String(std::string(a) + b.s_);
  }
};

struct SerialStub {
  void begin(int) {}
  void printf(const char*, ...) {}
  void println(const char* = "") {}
  void println(const String&) {}
  void print(const char*) {}
};
extern SerialStub Serial;

struct ESPStub {
  uint64_t getEfuseMac() { return 0; }
  void restart() {}
};
extern ESPStub ESP;

void pinMode(int, int);
void digitalWrite(int, int);
int digitalRead(int);
void delay(unsigned long);
unsigned long millis();
int analogReadMilliVolts(int);
#define ADC_11db 3
void analogSetPinAttenuation(int, int);
bool psramFound();
void* ps_malloc(size_t);
void configTime(long, long, const char*, const char*);
uint32_t esp_random();
