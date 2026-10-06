#pragma once
// OTA: manifest check + MD5-verified streaming flash into the inactive
// partition. Battery gate enforced here. Manifest policy in core/.
//
// Endpoints come from the paired server (Authorization: Bearer):
//   GET {server}/v1/device/ota/version       -> "build=N\n[version=X]\n[md5=...]\n"
//   GET {server}/v1/device/ota/firmware.bin  -> the binary
// A manual otaBase override in settings still works for local dev servers.
//
// The flash always targets the inactive OTA app partition; NVS (Wi-Fi
// credentials, server URL, device token) is a separate partition and is
// never touched, so pairing survives every update -- no re-flash or
// re-pair is ever needed after an OTA.
#include <Arduino.h>

#include "../core/OtaManifest.h"
#include "../hal/Board.h"

// Progress callback: pct goes 0..100 monotonically (coarse steps).
using OtaProgressCb = void (*)(uint8_t pct);

class OtaManager {
 public:
  explicit OtaManager(Board* board) : board_(board) {}

  // Silent auto-install path (default setting): check + install in one go.
  // Returns true if an update was installed (caller should reboot).
  // currentBuild: this firmware's build number (FW_BUILD).
  bool checkAndInstall(const char* serverUrl, const char* token,
                       uint32_t currentBuild);

  // Building blocks for the interactive (manual) update UI:
  // Fetch and parse the manifest. Returns false on network/parse failure
  // (lastError() set); a 404 (no update channel) returns false with no
  // error set.
  bool getManifest(const char* serverUrl, const char* token,
                   spectra::OtaManifest& manifest);
  // Download + MD5-verify + flash the manifest's firmware. progress may be
  // nullptr. Returns true on success (caller should reboot).
  bool installFromManifest(const char* serverUrl, const char* token,
                           const spectra::OtaManifest& manifest,
                           OtaProgressCb progress = nullptr);
  // False when the battery is too low to flash safely. Callers show their
  // own "battery too low" screen in that case.
  bool batteryGatePassed();

  String lastError() const { return lastError_; }

 private:
  Board* board_;
  String lastError_;

  bool flashFirmware(const char* url, const char* token,
                     const spectra::OtaManifest& manifest,
                     OtaProgressCb progress);
};
