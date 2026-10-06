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

 private:
  Board* board_;
  String serverUrl_;
  String fwVersion_;
  String lastError_;

  // POST a JSON body; on 2xx fills bodyOut and returns the HTTP code.
  int postJson(const char* path, const String& jsonBody, const char* token,
               String& bodyOut);
};
