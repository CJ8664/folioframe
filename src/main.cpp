// SpectraFrame v1 — EE02 + GDEB0709E01 7.09" Spectra 6.
//
// Wake → Wi-Fi → time → OTA → fetch → paint → deep sleep.
// Buttons: BTN1 portal, BTN2 fetch now, BTN3 pin/freeze toggle.
#include <Arduino.h>
#include <esp_sleep.h>

#include "../include/board_config.h"
#include "app/Config.h"
#include "app/FrameFetcher.h"
#include "app/OtaManager.h"
#include "app/Portal.h"
#include "app/PowerManager.h"
#include "app/TimeSync.h"
#include "core/UrlTemplate.h"
#include "hal/EE02Board.h"
#include "hal/Gdeb0709e01Panel.h"
#include "ui/StatusScreen.h"

#define FW_VERSION "1.0.0"
#define FW_BUILD 1

// RTC-persisted across deep sleep (cleared on power loss / reset button).
RTC_DATA_ATTR bool g_pinned = false;
RTC_DATA_ATTR uint32_t g_bootCount = 0;

static EE02Board board;
static Gdeb0709e01Panel panel;
static Config config;
static TimeSync timeSync;
static FrameFetcher fetcher(&board, &panel);
static OtaManager ota(&board);
static Portal portal(&board, &config);
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
      status.showPortal(("SF-Setup-" + board.deviceId()).c_str(),
                        "http://192.168.4.1");
      portal.ensureWiFi();
      bool dirty = portal.run(10 * 60 * 1000);
      if (!dirty) {
        panel.sleep();
        power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
      }
      // else fall through to fetch with new settings
    }
  }

  // Pinned: skip everything, fast re-arm (sven97 quickSleep lesson).
  if (g_pinned && cause == WakeCause::Timer) {
    power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
  }

  // --- Network ---
  if (!portal.ensureWiFi()) panic("Wi-Fi failed", "Check credentials");
  bool clockOk = timeSync.begin(config.get().timezone);
  if (!clockOk) Serial.println("WARN: clock not synced");

  // Quiet hours: sleep through, don't fetch.
  if (power.inQuietNow(config.get(), timeSync.utcOffsetMinutes())) {
    Serial.println("in quiet window, sleeping through");
    panel.sleep();
    power.sleepUntilNext(config.get(), timeSync.utcOffsetMinutes());
  }

  // --- OTA (battery-gated inside OtaManager; disabled when otaBase empty) ---
  if (config.get().otaBase[0]) {
    char versionUrl[600], fwUrl[600];
    snprintf(versionUrl, sizeof(versionUrl), "%s/version",
             config.get().otaBase);
    snprintf(fwUrl, sizeof(fwUrl), "%s/firmware.bin", config.get().otaBase);
    if (ota.checkAndInstall(versionUrl, fwUrl, FW_BUILD)) {
      Serial.println("OTA installed, rebooting");
      ESP.restart();
    }
  }

  // --- Fetch + paint ---
  Settings& s = config.get();
  PanelDims d = panel.dims();
  bool landscape = (s.orientation % 2) == 1;
  spectra::UrlTokens tok{(uint32_t)esp_random(), landscape ? d.height : d.width,
                         landscape ? d.width : d.height};
  std::string url = spectra::expandUrlTemplate(s.imageUrl, tok);
  Serial.printf("fetch %s\n", url.c_str());
  board.blinkLed(2);  // proof-of-life during the long fetch
  switch (fetcher.fetch(url.c_str(), s.etag)) {
    case FetchResult::Ok:
      if (panel.drawPacked4bpp(fetcher.data(), fetcher.len())) {
        strncpy(s.etag, fetcher.etag().c_str(), sizeof(s.etag) - 1);
        config.save();
        Serial.println("painted");
      } else {
        status.showError("Paint failed", "Frame rejected by panel");
      }
      break;
    case FetchResult::NotModified:
      Serial.println("304: image unchanged, keeping panel");
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
