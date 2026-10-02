#pragma once
// Fetches a packed-4bpp frame over HTTP with ETag caching.
// Owns one PSRAM buffer sized for the panel.
#include <Arduino.h>

#include "../hal/Board.h"
#include "../hal/Panel.h"

enum class FetchResult { Ok, NotModified, Error };

class FrameFetcher {
 public:
  FrameFetcher(Board* board, Panel* panel);
  bool begin();  // allocate PSRAM buffer
  FetchResult fetch(const char* url, const char* etag);
  const uint8_t* data() const { return buf_; }
  size_t len() const { return len_; }
  String etag() const { return etag_; }
  String lastError() const { return lastError_; }

 private:
  Board* board_;
  Panel* panel_;
  uint8_t* buf_ = nullptr;
  size_t bufSize_ = 0;
  size_t len_ = 0;
  String etag_;
  String lastError_;
};
