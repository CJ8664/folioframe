#pragma once
// OTA: manifest check + MD5-verified streaming flash into the inactive
// partition. Battery gate enforced here. Manifest policy in core/.
//
// Endpoints come from the paired server (Authorization: Bearer):
//   GET {server}/v1/device/ota/version       -> "build=N\n[md5=...]\n"
//   GET {server}/v1/device/ota/firmware.bin  -> the binary
// A manual otaBase override in settings still works for local dev servers.
#include <Arduino.h>

#include "../core/OtaManifest.h"
#include "../hal/Board.h"

class OtaManager {
 public:
  explicit OtaManager(Board* board) : board_(board) {}

  // Returns true if an update was installed (caller should reboot).
  // currentBuild: this firmware's build number (FW_BUILD).
  bool checkAndInstall(const char* serverUrl, const char* token,
                       uint32_t currentBuild);

  String lastError() const { return lastError_; }

 private:
  Board* board_;
  String lastError_;

  bool fetchManifest(const char* url, const char* token,
                     spectra::OtaManifest& manifest);
  bool flashFirmware(const char* url, const char* token,
                     const spectra::OtaManifest& manifest);
};
