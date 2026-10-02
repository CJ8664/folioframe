#pragma once
#include <functional>

#include "Arduino.h"
enum HTTPMethod { HTTP_GET, HTTP_POST, HTTP_ANY };
class WebServer {
 public:
  explicit WebServer(int) {}
  void on(const char*, std::function<void()>) {}
  void on(const char*, HTTPMethod, std::function<void()>) {}
  String arg(const char*) { return String(""); }
  bool hasArg(const char*) { return false; }
  void send(int, const char*, const String&) {}
  void handleClient() {}
  void begin() {}
  void stop() {}
};
