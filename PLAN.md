# SpectraFrame — Plan, Verification & Test Strategy

## 1. Goal

Build a single new firmware codebase that combines the **device-side feature superset**
extracted from 7 firmware projects (9 repos) into one modular, hardware-swappable,
well-tested firmware. First hardware target: **Seeed XIAO EE02 + Good Display
GDEB0709E01 7.09" Spectra 6** (the user's board + panel).

"Combine the features" is scoped honestly:

- **In scope (v1 firmware):** every *device-firmware* feature from the superset that is
  hardware-meaningful: panel drivers, image fetch, scheduling, quiet hours, power
  management, battery telemetry, provisioning, config portal, OTA, buttons, time
  sync, debug tooling.
- **In scope (v1 server):** `server/` companion service implementing the content
  sources and rendering the firmware cannot do itself: local folder albums,
  picsum.photos, URL templates, a PIL-rendered clock/weather dashboard
  (Open-Meteo, no key), Pillow-C Floyd-Steinberg/Bayer dithering to Spectra 6,
  packed-4bpp frame packing, rotation engine (unseen-first, no-repeat),
  quiet hours, ETag/304, and the PROTOCOL.md endpoints (`/frame`, `/version`,
  `/firmware.bin`) plus a web UI with preview.
- **Integration points, not rewrites:** Tesserae's 40-widget framework, mobile
  apps, Cloudflare backends. Any of them can feed the firmware via PROTOCOL.md.
- **v2 roadmap (seams prepared, not implemented):** on-device JPEG decode,
  BLE provisioning, touch input, MQTT transport, native Home Assistant API,
  Google Photos / Unsplash sources (API keys), face-detection smart crop.

## 2. Language decision

| Option | Efficiency | Ease of understanding | Ecosystem for this task | Verdict |
|---|---|---|---|---|
| **C++17 + Arduino framework** | Native speed; 960 KB frame ops in ms | `setup()`/`loop()`, huge tutorial base | WiFiManager, ESP32 `Update`, `Preferences`, Seeed_GFX2 (official 7.09" support) | **Chosen** |
| C + ESP-IDF | Max control, slightly leaner | Steeper; manual event loops, partition code | aitjcize/tesserae use it, but 3–5× boilerplate | Rejected: Arduino core runs on ESP-IDF anyway |
| MicroPython | Interpreted; 30 s refresh becomes minutes of dither time | Easiest syntax | No mature dual-controller Spectra 6 driver; RAM-hungry | Rejected: fails the efficiency bar |
| Rust (esp-rs) | Excellent (safe + fast) | Ownership learning curve | Thin e-paper driver ecosystem; no GDEB0709E01 driver | Rejected for v1; HAL seams allow a later port |
| ESPHome YAML | Good (generates C++) | Easiest config | Not "code": custom logic still needs C++; hard to unit-test | Rejected as the base |

**Decision: C++17 on the Arduino framework, built with PlatformIO.**
It is the only option that is both efficient (native, PSRAM-safe) and easy to
understand, and 4 of the 7 analyzed projects already use it.

## 3. Architecture — layers and swap seams

```
┌─────────────────────────────────────────────────┐
│ app/main.cpp        device state machine        │  wiring only
├─────────────────────────────────────────────────┤
│ ui/     StatusScreen   (portal/status pages)    │  swap: UI style
├─────────────────────────────────────────────────┤
│ app/    Config, Power, Time, Fetch, OTA, Portal │  swap: behaviors
├─────────────────────────────────────────────────┤
│ hal/    Board (EE02)   │   Panel (GDEB0709E01)  │  ★ SWAP SEAM: new board/
│         abstract IF    │   abstract IF          │  panel = new subclass
├─────────────────────────────────────────────────┤
│ core/   Scheduler, QuietHours, BatteryCurve,    │  pure logic, zero
│         UrlTemplate, OtaManifest  (no Arduino)  │  hardware deps → unit tested
└─────────────────────────────────────────────────┘
```

**Swap rules (enforced by code review, not just convention):**

1. `hal/Board` — abstract interface: `buttons()`, `batteryMilliVolts()`,
   `setPanelPower(bool)`, `led()`, `deepSleep(us)`, `wakeCause()`.
   Porting to a new board = one new subclass + pin map. No other file changes.
2. `hal/Panel` — abstract interface: `begin()`, `dims()`, `drawPacked4bpp(buf)`,
   `drawStatus(...)`, `sleep()`, `busy()`. Porting to a new panel = one new
   subclass (native init sequence or a Seeed_GFX2 target swap).
3. `core/` — pure C++17, `#include`-free of Arduino. Compiles on the host.
   All policy math (scheduling, quiet hours, battery %, URL tokens, OTA manifest
   ordering) lives here and is unit-tested to ~100%.
4. `app/` — Arduino-dependent behaviors composed from `hal` + `core`.
   Thin; no business logic that isn't delegated to `core/`.
5. Server protocol is versioned (`PROTOCOL.md`); frame format negotiation is
   explicit so future formats (JPEG-on-device) slot in without breaking v1.

## 4. Feature mapping: superset → v1

| Superset feature | v1 | Notes |
|---|---|---|
| GDEB0709E01 7.09" driver via official lib | ✅ | `Seeed_GFX2`, target `Seeed_ePaper_7INCH09_C`, PSRAM required |
| Dual-controller transport | ✅ | Inherited from Seeed_GFX2 driver |
| Packed 4bpp framebuffer (960 000 B) | ✅ | Panel-native scan order, streamed into PSRAM |
| URL template `{seed}`/`{width}`/`{height}` | ✅ | `core/UrlTemplate` |
| ETag / If-None-Match, 304 skips refresh | ✅ | `app/FrameFetcher` |
| Refresh interval 15 min–24 h | ✅ | `core/Scheduler` |
| Quiet-hours window, wrap midnight, sleep-through | ✅ | `core/QuietHours` |
| Deep sleep + timer/button wake | ✅ | `hal/Board`, `app/PowerManager` |
| Battery ADC + discharge-curve % | ✅ | `core/BatteryCurve` + `hal/Board` |
| OTA manifest check, MD5 verify, battery gate ≥40% | ✅ | `core/OtaManifest` + `app/OtaManager` |
| Captive-portal Wi-Fi provisioning | ✅ | WiFiManager |
| Single-page auto-save settings portal | ✅ | `app/Portal` (interval, URL, quiet hours, TZ, name, orientation) |
| 3 buttons, remappable, debounced | ✅ | `hal/Board` |
| NTP + POSIX timezone | ✅ | `app/TimeSync` |
| /debug JSON + serial logging | ✅ | `app/Portal`, status endpoint |
| On-panel status / onboarding screens | ✅ | `ui/StatusScreen` |
| Wake-cause + battery logging | ✅ | `app/PowerManager` |
| On-device JPEG decode | v2 | Seam: `Panel::drawJpeg()` hook; needs JPEGDecoder + dither module |
| BLE provisioning | v2 | Seam: `app/Provisioner` interface |
| Touch input | v2 | Seam: `hal/Board::touchRegions()` |
| MQTT / HA native API | v2 | Seam: `app/Reporter` interface |
| Partial refresh | driver-limited | Exposed via `Panel::supportsPartial()`; GDEB0709E01 init is full-refresh |
| Local folder albums | ✅ server | `server/sources/folder.py`, unseen-first rotation |
| picsum.photos / URL sources | ✅ server | `server/sources/picsum.py`, `url.py`, `{seed}` tokens |
| Clock/weather dashboard | ✅ server | `server/sources/dashboard.py` (Open-Meteo, no key) |
| Server-side dithering | ✅ server | Pillow-C Floyd-Steinberg + Bayer 8x8, measured-ish palette |
| Rotation engine | ✅ server | unseen-first, no-repeat-until-cycled, quiet hours, 304s |
| Google Photos / Unsplash | v2 server | needs API key / fragile scraping — documented, not built |

## 5. Plan verification (done before coding)

- [x] **Pin map** — EE02 panel signals from schematic: SCLK=7, MOSI=9, CS_M=44,
      CS_S=41, DC=10, BUSY=4, RST=38, EN=43. Seeed_GFX2's EE02 catalog entry
      owns these pins, so the firmware sets no panel pins directly.
- [x] **Memory budget** — 1200×1600×4 bpp = 960 000 B frame. XIAO ESP32S3 Plus
      has 8 MB octal PSRAM; frame lives in PSRAM, leaving ~7 MB headroom.
- [x] **Library support** — Seeed_GFX2 lists "7.09-inch ePaper Display (Spectra 6)"
      and driver IC `GDEB0709E01`; target enum `Seeed_ePaper_7INCH09_C`
      (research-verified Sep 2026; compile will confirm, one-line change if renamed).
- [x] **Power** — Deep sleep ~10 µA class; battery J3 pin 1 = + (schematic);
      OTA gated on battery ≥ 40% (sven97's brownout lesson).
- [x] **Network** — 2.4 GHz only (ESP32-S3); TLS optional per endpoint.
- [x] **Testability** — All policy logic isolated in `core/` with no Arduino
      dependency; hardware seams (`hal/`) are interfaces, mockable.

## 6. Test plan

**Level 1 — Native unit tests (run here, must pass):** every `core/` module.
Scheduler alignment math, quiet-hours wrap logic, battery-curve interpolation
and clamping, URL template expansion + validation, OTA manifest strict parsing
and version ordering, config field validators. Target: 100% of `core/`
functions covered. Runner: `tools/run_tests.sh` (g++, zero dependencies).

**Level 2 — Stub compile (run here, must pass):** entire `src/` compiled with
`g++ -fsyntax-only` against minimal Arduino API stubs (`test/stubs/`) to catch
type/signature errors in Arduino-dependent code without the ESP32 toolchain.

**Level 3 — Hardware checklist (documented, run on device):**
flash → portal → Wi-Fi join → NTP → frame fetch → panel refresh → deep-sleep
current → button wake → quiet-hours sleep-through → OTA manifest → OTA install.
`docs/HARDWARE_CHECKLIST.md`.

**Coverage rule:** no new `core/` function without a test; no `app/` behavior
without either a test or a checklist line.

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| `Seeed_ePaper_7INCH09_C` enum renamed | One-line change in `Gdeb0709e01Panel`; caught at compile |
| Packed-frame server doesn't exist yet | `PROTOCOL.md` documents the contract; `tools/frame_server.py` reference sender included |
| PSRAM not enabled | `setup()` asserts PSRAM and shows an on-panel error |
| OTA bricks device | ESP32 A/B partitions: bootloader rolls back on failed boot; manifest MD5 verified pre-flash |
| Feature creep | v2 list is explicit; v1 scope is frozen in §4 |
