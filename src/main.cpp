// FolioFrame v2 — EE02 + GDEB0709E01 7.09" Spectra 6.
//
// Wake → Wi-Fi → time → pair (first boot) → OTA → fetch → paint → sleep.
// The frame never fetches images directly: it pairs with the FolioFrame
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
#include "ui/StatusBadge.h"
#include "ui/StatusScreen.h"

#define FW_VERSION "0.0.23"
#define FW_BUILD 41

// RTC-persisted across deep sleep (cleared on power loss / reset button).
RTC_DATA_ATTR bool g_nextImage = false;
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

// OTA interaction state (fresh each boot; plain statics are fine).
static bool g_otaCheckNow = false;  // long-press KEY2: check for update now
static bool g_otaPrompt = false;    // short-press KEY2, manual mode, staged update
static int g_wifiRssi = -100;       // set after Wi-Fi connects
static uint8_t g_battPct = 0;       // 0 = unknown / no battery
static bool g_onUsb = false;
static uint8_t s_lastOtaPct = 255;

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

// Human label for an update: "v0.0.3 (build 20)", or "build 20" when the
// manifest carries no version string.
static void otaLabelForManifest(const spectra::OtaManifest& m, char* out,
                                size_t n) {
  if (!m.version.empty())
    snprintf(out, n, "v%s (build %u)", m.version.c_str(), m.build);
  else
    snprintf(out, n, "build %u", m.build);
}

static void otaLabelForPending(char* out, size_t n) {
  const Settings& s = config.get();
  if (s.otaPendingVersion[0])
    snprintf(out, n, "v%s (build %u)", s.otaPendingVersion,
             s.otaPendingBuild);
  else
    snprintf(out, n, "build %u", s.otaPendingBuild);
}

// A full e-paper refresh (~30 s) is expensive, so the on-screen bar moves in
// coarse steps; serial still gets every percent.
static void otaProgressCb(uint8_t pct) {
  Serial.printf("OTA: %u%%\n", pct);
  if (pct >= 100) {
    s_lastOtaPct = 100;
    status.showOtaVerifying();
  } else if (pct >= s_lastOtaPct + 50) {
    s_lastOtaPct = pct;
    status.showOtaProgress(pct);
  }
}

// KEY2 = install, KEY1 = skip. The entry hold may still be down, so require
// release first to avoid double-counting it as the confirmation press.
static bool waitForOtaConfirm() {
  uint32_t t0 = millis();
  while (board.buttonHeld(ButtonId::Btn2) && millis() - t0 < 5000) delay(50);
  t0 = millis();
  while (millis() - t0 < 15000) {
    switch (board.pollButton()) {
      case ButtonId::Btn2:
        return true;
      case ButtonId::Btn1:
        return false;
      default:
        break;
    }
    delay(50);
  }
  return false;  // timeout = skip, continue the normal cycle
}

static void showOtaManifestFailure() {
  if (ota.lastError().length()) {
    status.showOtaFailed(ota.lastError().c_str());
  } else {
    status.showOtaNoChannel();
  }
}

// Download + verify + flash, then reboot. NVS (Wi-Fi, server URL, device
// token) is untouched by the OTA partition swap, so the frame comes back
// already paired -- never a re-pair after an update.
static void installOtaUpdate(const char* otaServer, const char* otaToken,
                             const spectra::OtaManifest* manifest) {
  spectra::OtaManifest m;
  if (!manifest) {
    if (!ota.getManifest(otaServer, otaToken, m)) {
      showOtaManifestFailure();
      return;
    }
    if (!spectra::shouldUpdate(FW_BUILD, m)) {
      status.showOtaUpToDate();
      return;
    }
    manifest = &m;
  }
  if (!ota.batteryGatePassed()) {
    status.showOtaBatteryLow();
    return;
  }
  s_lastOtaPct = 0;
  status.showOtaProgress(0);
  if (ota.installFromManifest(otaServer, otaToken, *manifest, otaProgressCb)) {
    config.get().otaUpdatePending = false;  // installed: nothing staged
    config.save();
    status.showOtaDone();  // blocks for the e-paper refresh
    Serial.println("OTA installed, rebooting");
    ESP.restart();
  } else {
    status.showOtaFailed(ota.lastError().c_str());
  }
}

// Interactive OTA entry points:
//   check-now   = long-press KEY2: fresh manifest check, then prompt.
//   prompt-only = manual mode with a staged update: straight to the prompt.
// Installs reboot; anything else falls through to the normal cycle.
static void runOtaInteractive(const char* otaServer, const char* otaToken,
                              bool promptOnly) {
  if (promptOnly) {
    char label[48];
    otaLabelForPending(label, sizeof(label));
    status.showUpdatePrompt(label);
    if (waitForOtaConfirm()) {
      installOtaUpdate(otaServer, otaToken, nullptr);
    } else {
      // Dismissed: clear the staged flag. The next wake re-checks the
      // manifest and re-stages if the update is still there.
      config.get().otaUpdatePending = false;
      config.save();
      Serial.println("OTA: staged update dismissed");
    }
    return;
  }
  status.showOtaChecking();
  if (!ota.batteryGatePassed()) {
    status.showOtaBatteryLow();
    return;
  }
  spectra::OtaManifest manifest;
  if (!ota.getManifest(otaServer, otaToken, manifest)) {
    showOtaManifestFailure();
    return;
  }
  if (!spectra::shouldUpdate(FW_BUILD, manifest)) {
    status.showOtaUpToDate();
    return;
  }
  char label[48];
  otaLabelForManifest(manifest, label, sizeof(label));
  status.showOtaAvailable(label);
  if (waitForOtaConfirm()) {
    installOtaUpdate(otaServer, otaToken, &manifest);
  } else {
    Serial.println("OTA: skipped by user");
  }
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
  // Capture the KEY2 press timestamp as early as possible: the 2.5 s
  // long-press hold is measured from the physical press (GPIO interrupt),
  // not from whenever setup() gets around to checking after panel init.
  // Falls back to the earliest post-boot observation when the press woke
  // the chip from deep sleep (no ISR fires in sleep).
  uint32_t btn2DownAt = 0;
  if (board.buttonHeld(ButtonId::Btn2)) {
    uint32_t ts = board.buttonPressMs(ButtonId::Btn2);
    btn2DownAt = (ts != 0) ? ts : millis();
  }
  Serial.begin(115200);
  Serial.printf("FolioFrame %s build %u boot %u\n", FW_VERSION, FW_BUILD,
                g_bootCount);

  if (!psramFound()) panic("No PSRAM", "Enable PSRAM in Tools menu");
  if (!panel.begin()) panic("Panel init failed", "Check FPC connection");
  if (!fetcher.begin()) panic("No frame buffer", "PSRAM allocation failed");
  config.load();

  // A firmware update invalidates the photo ETag: the panel may be showing
  // a stale non-photo screen (setup/settings), so force one repaint instead
  // of 304-keeping it.
  {
    Settings& sc = config.get();
    if (sc.fwBuild != FW_BUILD) {
      sc.fwBuild = FW_BUILD;
      sc.etag[0] = '\0';
      config.save();
      Serial.println("fw build changed, cleared photo ETag");
    }
  }

  WakeCause cause = board.wakeCause();
  Serial.printf("wake cause: %d\n", (int)cause);

  // --- Battery (before any radio work) ---
  g_onUsb = board.usbPowered();
  if (!g_onUsb) {
    uint16_t battMv = board.batteryMilliVolts();
    g_battPct = board.batteryPercent();
    // A valid reading at/below the curve floor (pct 0 but mv > 0) is a
    // genuinely dead battery, not an unknown one: sleep instead of
    // waking and fetching on 3.3V.
    bool deadBattery = battMv > 0 && g_battPct == 0;
    if (deadBattery || (g_battPct > 0 && g_battPct < 15)) {
      status.showCriticalBattery();
      panel.sleep();
      board.deepSleep((uint64_t)30 * 60 * 1000000ULL);  // retry in 30 min
    } else if (g_battPct > 0 && g_battPct < 30) {
      status.showLowBattery(g_battPct);  // warn, then continue normally
    }
  }

  // --- Button wakes ---
  // KEY1: wake only — the normal cycle below runs (refresh now).
  // KEY2: short press = settings portal; long hold (2.5 s) = check for a
  // firmware update now; short press with a staged manual update = install
  // prompt. KEY3: next image (server rotates to the next photo).
  if (cause == WakeCause::Button) {
    bool key2Settings = false;
    switch (wakeButton()) {
      case ButtonId::Btn1:
        break;  // wake only
      case ButtonId::Btn2: {
        bool longPress = board.buttonHeld(ButtonId::Btn2) &&
                         btn2DownAt != 0 && (millis() - btn2DownAt >= 2500);
        if (longPress) {
          g_otaCheckNow = true;
        } else if (!config.get().otaAutoInstall &&
                   config.get().otaUpdatePending) {
          g_otaPrompt = true;
        } else {
          key2Settings = true;
        }
        break;
      }
      case ButtonId::Btn3:
        g_nextImage = true;  // force server rotation to the next photo
        Serial.println("next image requested");
        break;
      default:
        break;
    }
    // KEY2 (short press) opens the settings portal — but only once paired.
    // On an unpaired frame the portal would park on the settings screen
    // (then sleep) instead of making progress toward pairing, so unpaired
    // KEY2 presses just run the normal setup flow below, which ends at the
    // pairing screen.
    if (key2Settings && config.deviceToken().length()) {
      if (!portal.hasWiFiCreds()) {
        status.showPortal(("FF-Setup-" + board.deviceId()).c_str(),
                          "http://192.168.4.1");
      }
      portal.ensureWiFi();
      // Show the reachable address: AP IP when in setup mode, LAN address
      // when on home Wi-Fi. WiFi.localIP() is 0.0.0.0 in AP mode.
      String url;
      if (WiFi.getMode() & WIFI_AP) {
        url = "http://" + WiFi.softAPIP().toString();
      } else {
        url = "http://" + WiFi.localIP().toString();
      }
      status.showSettings(url.c_str());
      bool dirty = portal.run(10 * 60 * 1000);
      if (!dirty) {
        panel.sleep();
        power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes(),
                             false /* clock not synced yet */);
      }
      // else fall through with the new settings
    }
  }

  // --- Network ---
  // No Wi-Fi credentials yet (very first boot): point the user at the
  // setup AP before WiFiManager starts its captive portal. We check our
  // own server-URL config too: on a fresh boot both are blank, and the
  // WiFiManager saved-state check alone has proven unreliable.
  bool hasCreds = portal.hasWiFiCreds();
  bool hasServer = strlen(config.get().serverUrl) > 0;
  bool paired = config.deviceToken().length() > 0;
  Serial.printf("netcheck: hasWiFiCreds=%d hasServerUrl=%d paired=%d\n",
                (int)hasCreds, (int)hasServer, (int)paired);
  // The WiFiManager saved-state check is unreliable (it reports no creds
  // while the ESP32 NVS creds connect fine). A paired frame never needs the
  // setup screen: if WiFi is truly down, ensureWiFi shows the portal. And a
  // setup screen drawn on a paired frame would leave a stale non-photo
  // image that a later 304 would never repaint.
  if ((!hasCreds || !hasServer) && !paired) {
    Serial.println("netcheck: drawing setup screen");
    status.showPortal(("FF-Setup-" + board.deviceId()).c_str(),
                      "http://192.168.4.1");
    Serial.println("netcheck: setup screen done");
    // The panel no longer shows the photo the ETag refers to.
    Settings& sc = config.get();
    sc.etag[0] = '\0';
    config.save();
  } else {
    Serial.println("netcheck: skipping setup screen");
  }
  if (!portal.ensureWiFi()) {
    status.showWiFiLost();
    panel.sleep();
    board.deepSleep((uint64_t)15 * 60 * 1000000ULL);  // retry in 15 min
  }
  g_wifiRssi = WiFi.RSSI();
  Serial.printf("wifi rssi: %d dBm\n", g_wifiRssi);
  if (g_wifiRssi < -75) status.showWiFiWeak(g_wifiRssi);  // warn, continue
  Settings& s = config.get();

  bool clockOk = timeSync.begin(config.get().timezone);
  if (!clockOk) Serial.println("WARN: clock not synced");

  // --- Server URL: required before anything else. First boot (or a wipe)
  // drops into the settings portal so the user can type it. The portal
  // runs on the home Wi-Fi at this point, so show the frame's real LAN
  // address -- not the setup-AP address.
  while (!s.serverUrl[0]) {
    String url;
    if (WiFi.getMode() & WIFI_AP) {
      url = "http://" + WiFi.softAPIP().toString();
    } else {
      url = "http://" + WiFi.localIP().toString();
    }
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

  // DeviceClient needs the server URL + firmware version for telemetry on
  // every paired wake, not just inside the pairing flow.
  deviceClient.begin(s.serverUrl, FW_VERSION);

  // Quiet hours: sleep through, don't fetch. Fail open when the clock
  // didn't sync: 1970 timestamps must never trigger a sleep-through.
  // Never sleep through setup: an unpaired frame (no device token) always
  // continues to the pairing screen — the user is standing right there.
  // Development: on USB power quiet hours are skipped entirely.
  String token = config.deviceToken();
  if (clockOk && token.length() && !g_onUsb &&
      power.inQuietNow(config.get(), timeSync.utcOffsetMinutes())) {
    Serial.println("in quiet window, sleeping through");
    panel.sleep();
    power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes(), clockOk);
  }

  // --- Pairing (first boot, after unpair, or after a revoked token) ---
  if (!token.length()) {
    token = pairWithServer(s.serverUrl);
    if (!token.length()) {
      panel.sleep();
      board.deepSleep((uint64_t)15 * 60 * 1000000ULL);  // retry in 15 min
    }
    config.setDeviceToken(token);
  }

  // --- OTA ---
  // Manual otaBase overrides the paired server (local dev); otherwise the
  // paired server serves version + binary, authenticated like frames.
  const char* otaServer = s.otaBase[0] ? s.otaBase : s.serverUrl;
  const char* otaToken = s.otaBase[0] ? "" : token.c_str();
  // Report telemetry first so the console shows this device's firmware
  // version even if the OTA or fetch below fails.
  deviceClient.sendStatus(token.c_str(), FW_BUILD);
  // Server-wins auto-update: the web console toggle is the source of truth
  // and overwrites the local NVS flag for this wake. Persist it so a later
  // Portal visit shows the effective value.
  bool serverAutoUpdate = deviceClient.lastAutoUpdate(s.otaAutoInstall);
  if (serverAutoUpdate != s.otaAutoInstall) {
    s.otaAutoInstall = serverAutoUpdate;
    config.save();
    Serial.printf("OTA: auto-install %s (from server)\n",
                  s.otaAutoInstall ? "ON" : "OFF");
  }
  // Website-managed device settings: the web console is the source of truth
  // once paired. Only keys actually present in the heartbeat response
  // override the local NVS values (offline fallback). Applies from the next
  // wake: this wake's schedule/clock were already decided above.
  {
    ServerDeviceSettings ss;
    if (deviceClient.lastServerSettings(ss)) {
      Settings cand = config.get();
      bool changed = false;
      if (ss.hasInterval && cand.intervalMinutes != ss.intervalMinutes) {
        cand.intervalMinutes = ss.intervalMinutes;
        changed = true;
      }
      if (ss.hasQuietEnabled && cand.quietEnabled != ss.quietEnabled) {
        cand.quietEnabled = ss.quietEnabled;
        changed = true;
      }
      if (ss.hasQuietStart && cand.quietStartMin != ss.quietStartMin) {
        cand.quietStartMin = ss.quietStartMin;
        changed = true;
      }
      if (ss.hasQuietEnd && cand.quietEndMin != ss.quietEndMin) {
        cand.quietEndMin = ss.quietEndMin;
        changed = true;
      }
      if (ss.hasTimezone && String(cand.timezone) != String(ss.timezone)) {
        strncpy(cand.timezone, ss.timezone, sizeof(cand.timezone) - 1);
        cand.timezone[sizeof(cand.timezone) - 1] = '\0';
        changed = true;
      }
      if (ss.hasOrientation && cand.orientation != ss.orientation) {
        cand.orientation = ss.orientation;
        changed = true;
      }
      if (changed) {
        String err;
        if (Config::validate(cand, err)) {
          config.get() = cand;
          config.save();
          Serial.println("applied website device settings");
        } else {
          Serial.printf("website device settings rejected: %s\n", err.c_str());
        }
      }
    }
  }
  if (g_otaCheckNow || g_otaPrompt) {
    // Button-driven: an install reboots; anything else falls through to
    // the normal fetch cycle.
    runOtaInteractive(otaServer, otaToken, g_otaPrompt && !g_otaCheckNow);
  } else if (s.otaAutoInstall) {
    // Default: silent auto-install, no buttons needed.
    if (ota.checkAndInstall(otaServer, otaToken, FW_BUILD)) {
      config.get().otaUpdatePending = false;  // nothing staged anymore
      config.save();
      Serial.println("OTA installed, rebooting");
      ESP.restart();
    }
  } else {
    // Manual mode: check only. A newer build is staged in NVS (survives
    // deep sleep) so a short KEY2 press can prompt for it; nothing is
    // installed without the user.
    spectra::OtaManifest manifest;
    if (ota.getManifest(otaServer, otaToken, manifest) &&
        spectra::shouldUpdate(FW_BUILD, manifest)) {
      // Read-compare-write inside savePendingUpdate(): re-staging the same
      // update on every wake must not cost an NVS write each time.
      config.savePendingUpdate(true, manifest.build, manifest.version.c_str());
      Serial.printf("OTA: update staged: build %u\n", manifest.build);
    }
  }

  // --- Fetch + paint ---
  // KEY3: ask the server to rotate to the next photo first. The rotation
  // changes the frame ETag, so the fetch below naturally gets a 200.
  if (g_nextImage) {
    g_nextImage = false;
    Serial.println("requesting next image from server");
    if (!deviceClient.nextImage(token.c_str())) {
      Serial.printf("next image failed: %s\n",
                    deviceClient.lastError().c_str());
    }
  }
  board.blinkLed(2);  // proof-of-life during the long fetch
  switch (fetcher.fetchFrame(s.serverUrl, token.c_str(), FW_VERSION,
                             s.etag)) {
    case FetchResult::Ok: {
      // Composite the corner status badge (Wi-Fi, battery, update dot)
      // into the frame buffer before the panel paint.
      uint8_t badgeBatt = g_onUsb ? 100 : g_battPct;
      PanelDims dims = panel.dims();
      spectra::drawStatusBadge(const_cast<uint8_t*>(fetcher.data()),
                               fetcher.len(), dims.width, dims.height,
                               g_wifiRssi, badgeBatt,
                               config.get().otaUpdatePending);
      if (panel.drawPacked4bpp(fetcher.data(), fetcher.len())) {
        strncpy(s.etag, fetcher.etag().c_str(), sizeof(s.etag) - 1);
        s.etag[sizeof(s.etag) - 1] = '\0';
        config.save();
        Serial.println("painted");
      } else {
        status.showRenderError("The frame rejected the image.");
      }
      break;
    }
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
  if (g_onUsb) {
    // Development mode: on USB power never deep-sleep. The serial monitor
    // stays alive and any button press restarts the cycle — no wake/sleep
    // dance while iterating. Unplug to resume normal battery behavior.
    Serial.println("USB dev mode: staying awake, press any key to re-run");
    while (true) {
      if (board.pollButton() != ButtonId::None) {
        Serial.println("dev mode: button pressed, restarting cycle");
        delay(500);  // debounce
        ESP.restart();
      }
      delay(50);
    }
  }
  power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes(), clockOk);
}

void loop() {
  // Unreachable in normal use: setup() always ends in deep sleep (or the
  // USB dev-mode poll loop above).
}
