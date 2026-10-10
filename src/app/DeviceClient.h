#pragma once
// DeviceClient: speaks the FolioFrame v2 device API against the paired
// server (the URL in Settings::serverUrl).
//
//   POST {server}/v1/device/register   {device_id,panel,fw} -> claim code
//   POST {server}/v1/device/claim      {device_id,claim_code} -> pending |
//                                                                claimed + token
//   POST {server}/v1/device/unpair    (Authorization: Bearer) -> forget me
//
// The human finishes pairing in the web console: they type the claim code
// shown on the e-paper screen, and this client polls until the server hands
// over the device token. The token is returned to the caller; Config keeps
// it in a separate NVS namespace from the display settings.
#include <Arduino.h>

#include "../core/JsonLite.h"
#include "../hal/Board.h"

enum class ClaimState {
  Pending,   // human hasn't claimed us yet (or code wrong/expired: same shape)
  Claimed,   // server returned a device token
  HttpError,
};

struct RegisterResult {
  bool ok = false;
  String claimCode;  // "XXXX-XXXX" as shown on screen
  int expiresInSec = 0;
  String err;
};

struct ClaimResult {
  ClaimState state = ClaimState::HttpError;
  String token;  // set when state == Claimed
  String err;
};

// Website-managed device settings, piggybacked on the sendStatus heartbeat
// response. The web console is the source of truth once paired; only keys
// actually present in the response are marked and override the local NVS
// values (offline fallback).
struct ServerDeviceSettings {
  bool hasInterval = false;
  uint32_t intervalMinutes = 0;
  bool hasQuietEnabled = false;
  bool quietEnabled = false;
  bool hasQuietStart = false;
  int quietStartMin = 0;
  bool hasQuietEnd = false;
  int quietEndMin = 0;
  bool hasTimezone = false;
  char timezone[65] = {0};
  bool hasOrientation = false;
  uint8_t orientation = 0;
};

class DeviceClient {
 public:
  explicit DeviceClient(Board* board) : board_(board) {}

  // serverUrl like "https://frame.example.com" (no trailing slash).
  void begin(const char* serverUrl, const char* fwVersion);

  RegisterResult registerDevice();
  ClaimResult pollClaim(const char* claimCode);
  bool unpair(const char* token);  // true on 200
  // Report telemetry (firmware version, battery, signal). Best-effort:
  // failures never block the wake cycle. Powers the console's firmware
  // version display and update-available badge.
  bool sendStatus(const char* token, uint32_t fwBuild);

  String lastError() const { return lastError_; }
  String fwVersion() const { return fwVersion_; }
  // Auto-update setting from the last sendStatus response's settings object.
  // Returns dflt when the server sent no setting (old server): the caller
  // passes the local NVS value so it is preserved.
  bool lastAutoUpdate(bool dflt) const;
  // Website-managed settings from the last sendStatus response. Only keys
  // actually present are marked in `out`; absent keys keep local values.
  // Returns false when no status response is available.
  bool lastServerSettings(ServerDeviceSettings& out) const;

 private:
  Board* board_;
  String serverUrl_;
  String fwVersion_;
  String lastError_;
  String lastStatusBody_;  // raw body of the last sendStatus response

  // POST a JSON body; on 2xx fills bodyOut and returns the HTTP code.
  int postJson(const char* path, const String& jsonBody, const char* token,
               String& bodyOut);
};
