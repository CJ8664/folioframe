// SpectraFrame v2 — EE02 + GDEB0709E01 7.09" Spectra 6.
//
// Wake → Wi-Fi → time → pair (first boot) → OTA → fetch → paint → sleep.
// The frame never fetches images directly: it pairs with the SpectraFrame
// server (claim code shown on the e-paper screen, typed into the web
// console), then polls GET /v1/device/frame with its device Bearer token.
// The server renders whatever source the user picked (Google Photos,
// local album, ...) into packed 4bpp for this panel.
//
// Buttons: BTN1 portal/settings, BTN2 fetch now, BTN3 pin/freeze toggle.
#include <Arduino.h>
#include <WiFi.h>
#include <esp_sleep.h>

#include "../include/board_config.h"
#include "app/Config.h"
#include "app/DeviceClient.h"
#include "app/FrameFetcher.h"
#include "app/OtaManager.h"
#include "app/Portal.h"
#include "app/PowerManager.h"
#include "app/TimeSync.h"
#include "hal/EE02Board.h"
#include "hal/Gdeb0709e01Panel.h"
#include "ui/StatusScreen.h"

#define FW_VERSION "3.8.0"
#define FW_BUILD 11

// RTC-persisted across deep sleep (cleared on power loss / reset button).
RTC_DATA_ATTR bool g_pinned = false;
RTC_DATA_ATTR uint32_t g_bootCount = 0;

static EE02Board board;
static Gdeb0709e01Panel panel;
static Config config;
static TimeSync timeSync;
static DeviceClient deviceClient(&board);
static FrameFetcher fetcher(&board, &panel);
static OtaManager ota(&board);
static Portal portal(&board, &config, &deviceClient);
static PowerManager power(&board);
static StatusScreen status(&panel);

static ButtonId wakeButton() {
  uint64_t pins = esp_sleep_get_ext1_wakeup_status();
  if (pins & (1ULL << EE02_KEY1_PIN)) return ButtonId::Btn1;
  if (pins & (1ULL << EE02_KEY2_PIN)) return ButtonId::Btn2;
  if (pins & (1ULL << EE02_KEY3_PIN)) return ButtonId::Btn3;
  return ButtonId::None;
}

static void panic(const char* title, const char* detail) {
  status.showError(title, detail);
  panel.sleep();
  board.deepSleep((uint64_t)15 * 60 * 1000000ULL);  // retry in 15 min
}

// Pairing: register with the server, show the claim code on the panel,
// poll until the human claims us in the web console. Blocks (with the
// panel showing the code) until claimed or the code expires.
static String pairWithServer(const char* serverUrl) {
  deviceClient.begin(serverUrl, FW_VERSION);
  for (int attempt = 0; attempt < 3; attempt++) {
    RegisterResult reg = deviceClient.registerDevice();
    if (!reg.ok) {
      Serial.printf("register failed: %s\n", reg.err.c_str());
      status.showError("Pairing failed", reg.err.c_str());
      return "";
    }
    Serial.printf("claim code %s (expires in %ds)\n", reg.claimCode.c_str(),
                  reg.expiresInSec);
    status.showPairing(reg.claimCode.c_str(), serverUrl);

    uint32_t start = millis();
    while (millis() - start < (uint32_t)reg.expiresInSec * 1000UL) {
      delay(10000);  // poll every 10 s; the e-paper keeps showing the code
      ClaimResult claim = deviceClient.pollClaim(reg.claimCode.c_str());
      if (claim.state == ClaimState::Claimed) {
        Serial.println("paired");
        status.showPaired();
        return claim.token;
      }
      if (claim.state == ClaimState::HttpError) {
        Serial.printf("claim poll error: %s\n", claim.err.c_str());
        // Keep polling: transient network errors shouldn't kill pairing.
      }
    }
    Serial.println("claim code expired, re-registering");
  }
  status.showError("Pairing timed out", "Try again on next wake.");
  return "";
}

void setup() {
  g_bootCount++;
  board.begin();
  Serial.begin(115200);
  Serial.printf("SpectraFrame %s build %u boot %u\n", FW_VERSION, FW_BUILD,
                g_bootCount);

  if (!psramFound()) panic("No PSRAM", "Enable PSRAM in Tools menu");
  if (!panel.begin()) panic("Panel init failed", "Check FPC connection");
  if (!fetcher.begin()) panic("No frame buffer", "PSRAM allocation failed");
  config.load();

  WakeCause cause = board.wakeCause();
  Serial.printf("wake cause: %d\n", (int)cause);

  // --- Button wakes ---
  if (cause == WakeCause::Button) {
    switch (wakeButton()) {
      case ButtonId::Btn1:
        break;  // handled below: enter portal
      case ButtonId::Btn2:
        break;  // force a fetch this cycle
      case ButtonId::Btn3:
        g_pinned = !g_pinned;
        Serial.printf("pinned=%d\n", g_pinned);
        break;
      default:
        break;
    }
    if (wakeButton() == ButtonId::Btn1) {
      if (!portal.hasWiFiCreds()) {
        status.showPortal(("SF-Setup-" + board.deviceId()).c_str(),
                          "http://192.168.4.1");
      }
      portal.ensureWiFi();
      // The settings portal runs on the home Wi-Fi: show the LAN address.
      String url = "http://" + WiFi.localIP().toString();
      status.showSettings(url.c_str());
      bool dirty = portal.run(10 * 60 * 1000);
      if (!dirty) {
        panel.sleep();
        power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
      }
      // else fall through with the new settings
    }
  }

  // Pinned: skip everything, fast re-arm (sven97 quickSleep lesson).
  if (g_pinned && cause == WakeCause::Timer) {
    power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
  }

  // --- Network ---
  // No Wi-Fi credentials yet (very first boot): point the user at the
  // setup AP before WiFiManager starts its captive portal. We check our
  // own server-URL config too: on a fresh boot both are blank, and the
  // WiFiManager saved-state check alone has proven unreliable.
  bool hasCreds = portal.hasWiFiCreds();
  bool hasServer = strlen(config.get().serverUrl) > 0;
  Serial.printf("netcheck: hasWiFiCreds=%d hasServerUrl=%d\n",
                (int)hasCreds, (int)hasServer);
  if (!hasCreds || !hasServer) {
    Serial.println("netcheck: drawing setup screen");
    status.showPortal(("SF-Setup-" + board.deviceId()).c_str(),
                      "http://192.168.4.1");
    Serial.println("netcheck: setup screen done");
  } else {
    Serial.println("netcheck: skipping setup screen");
  }
  if (!portal.ensureWiFi()) panic("Wi-Fi failed", "Check credentials");
  bool clockOk = timeSync.begin(config.get().timezone);
  if (!clockOk) Serial.println("WARN: clock not synced");

  Settings& s = config.get();

  // --- Server URL: required before anything else. First boot (or a wipe)
  // drops into the settings portal so the user can type it. The portal
  // runs on the home Wi-Fi at this point, so show the frame's real LAN
  // address -- not the setup-AP address.
  while (!s.serverUrl[0]) {
    String url = "http://" + WiFi.localIP().toString();
    status.showSettings(url.c_str());
    portal.run(10 * 60 * 1000);
    config.load();  // re-read; portal saved to NVS
    s = config.get();
    if (!s.serverUrl[0]) {
      status.showError("No server URL", "Set it in the portal, retrying.");
      panel.sleep();
      board.deepSleep((uint64_t)15 * 60 * 1000000ULL);
    }
  }

  // Quiet hours: sleep through, don't fetch.
  if (power.inQuietNow(config.get(), timeSync.utcOffsetMinutes())) {
    Serial.println("in quiet window, sleeping through");
    panel.sleep();
    power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
  }

  // --- Pairing (first boot, after unpair, or after a revoked token) ---
  String token = config.deviceToken();
  if (!token.length()) {
    token = pairWithServer(s.serverUrl);
    if (!token.length()) {
      panel.sleep();
      board.deepSleep((uint64_t)15 * 60 * 1000000ULL);  // retry in 15 min
    }
    config.setDeviceToken(token);
  }

  // --- OTA (battery-gated inside OtaManager) ---
  // Manual otaBase overrides the paired server (local dev); otherwise the
  // paired server serves version + binary, authenticated like frames.
  const char* otaServer = s.otaBase[0] ? s.otaBase : s.serverUrl;
  const char* otaToken = s.otaBase[0] ? "" : token.c_str();
  // Report telemetry first so the console shows this device's firmware
  // version even if the OTA or fetch below fails.
  deviceClient.sendStatus(token.c_str(), FW_BUILD);
  if (ota.checkAndInstall(otaServer, otaToken, FW_BUILD)) {
    Serial.println("OTA installed, rebooting");
    ESP.restart();
  }

  // --- Fetch + paint ---
  board.blinkLed(2);  // proof-of-life during the long fetch
  switch (fetcher.fetchFrame(s.serverUrl, token.c_str(), FW_VERSION,
                             s.etag)) {
    case FetchResult::Ok:
      if (panel.drawPacked4bpp(fetcher.data(), fetcher.len())) {
        strncpy(s.etag, fetcher.etag().c_str(), sizeof(s.etag) - 1);
        s.etag[sizeof(s.etag) - 1] = '\0';
        config.save();
        Serial.println("painted");
      } else {
        status.showError("Paint failed", "Frame rejected by panel");
      }
      break;
    case FetchResult::NotModified:
      Serial.println("304: image unchanged, keeping panel");
      break;
    case FetchResult::Unauthorized:
      // Owner unpaired us (or the token got wiped server-side): drop the
      // token and re-pair on next wake. Never loop here -- the panel keeps
      // showing the last good image.
      Serial.println("token rejected, clearing for re-pair");
      config.clearDeviceToken();
      status.showError("Unpaired", "Pair again from the web console.");
      break;
    case FetchResult::Error:
      Serial.printf("fetch error: %s\n", fetcher.lastError().c_str());
      // Keep the current image; retry next wake (all superset firmwares).
      break;
  }

  panel.sleep();
  power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
}

void loop() {
  // Unreachable: setup() always ends in deep sleep.
}
