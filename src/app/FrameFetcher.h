#pragma once
// Fetches a packed-4bpp frame from the paired FolioFrame server with
// ETag caching. Owns one PSRAM buffer sized for the panel.
//
//   GET {serverUrl}/v1/device/frame   Authorization: Bearer <device token>
//
// The server renders the current source (Google Photos, local album, ...)
// into the panel's exact packed-4bpp format; the firmware never fetches
// image URLs directly.
#include <Arduino.h>

#include "../hal/Board.h"
#include "../hal/Panel.h"

enum class FetchResult {
  Ok,
  NotModified,  // 304: panel already shows this frame
  Unauthorized,  // 401: token rejected -- caller must re-pair
  Error,
};

class FrameFetcher {
 public:
  FrameFetcher(Board* board, Panel* panel);
  bool begin();  // allocate PSRAM buffer
  FetchResult fetchFrame(const char* serverUrl, const char* token,
                         const char* fwVersion, const char* etag);
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
