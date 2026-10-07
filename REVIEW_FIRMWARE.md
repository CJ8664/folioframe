# FolioFrame Firmware Code Review

**Date:** 2026-10-07 · **Scope:** `src/app/`, `src/core/`, `src/hal/`, `include/board_config.h`
**Reviewer:** automated deep review (subagent) + open-source library research
**Method:** every file read in full; ESP32 Arduino core sources checked for API contracts (Update.h); Seeed_GFX vs Seeed_GFX2 migration path verified against Seeed's own README.

---

## 1. Critical issues (fix before next release)

### 1.1 OTA MD5 verification is broken — `Update.setMD5` gets binary bytes, not a hex string

**File:** `src/app/OtaManager.cpp:95-104`

```cpp
if (manifest.hasMd5) {
    uint8_t md5[16];
    for (int i = 0; i < 16; i++) {
      char byte[3] = {manifest.md5[2 * i], manifest.md5[2 * i + 1], 0};
      md5[i] = (uint8_t)strtoul(byte, nullptr, 16);
    }
    Update.setMD5((const char*)md5);   // <-- BUG
}
```

**Why it's wrong:** ESP32 Arduino core `Update.h` documents `setMD5` as
`@param expected_md5 Hex string containing expected MD5 digest` (verified
against espressif/arduino-esp32 master `libraries/Update/src/Update.h`).
The code hex-*decodes* the manifest's 32-char MD5 into 16 **binary** bytes
and casts the buffer to `const char*`.

Consequences:
- `setMD5` receives 16 non-NUL-terminated binary bytes where it expects a
  32-char hex string. The core validates `strlen(expected_md5) != 32` →
  returns false, so **no MD5 is registered at all**.
- `strlen` on a non-terminated 16-byte stack buffer is a **stack buffer
  over-read** (reads past `md5[16]` until a coincidental NUL byte).
- Net effect: the "MD5-verified streaming flash" claim in
  `src/app/OtaManager.h` is **false in practice**. OTA updates are accepted
  on size + ESP-IDF image-header checks only. A corrupted/truncated binary
  that still has a valid header would flash.

**Fix:**
```cpp
if (manifest.hasMd5) {
    if (!Update.setMD5(manifest.md5.c_str())) {
      lastError_ = "bad MD5 in manifest";
      Update.abort();
      http.end();
      return false;
    }
}
```
`manifest.md5` is already validated as 32 lowercase hex chars by
`validMd5()` in `src/core/OtaManifest.cpp:26-32`, so it can be passed
through directly. Also handle the `false` return — currently the return
value is ignored entirely.

**Severity:** critical (security/integrity + memory safety). This is the
single most important finding of the review.

### 1.2 Hardcoded panel GPIO numbers in `Gdeb0709e01Panel::begin()`

**File:** `src/hal/Gdeb0709e01Panel.cpp:42-53`

```cpp
pinMode(43, OUTPUT);   // EN
...
pinMode(38, OUTPUT);   // RST
...
Serial.printf("panel pre-begin, BUSY=%d\n", digitalRead(4));  // BUSY
```

`include/board_config.h` explicitly says panel FPC signals
(SCLK=7, MOSI=9, CS_M=44, CS_S=41, DC=10, BUSY=4, RST=38, EN=43) are
"owned by the Seeed_GFX2 product catalog — do NOT redefine them here."
But `begin()` re-implements EN/RST sequencing with **magic numbers** that
are not named constants anywhere. If the board revision changes these
pins, there are now two places to update and nothing ties them together.

**Fix:** either delete the manual sequencing (let the driver own it — the
comment at line 40-41 already says "The old library's setup handles
EN/RST via the board config") or move the numbers into
`board_config.h` as `EE02_PANEL_EN_PIN` / `EE02_PANEL_RST_PIN` /
`EE02_PANEL_BUSY_PIN`.

**Severity:** medium (maintainability; also the manual `delay(500)` + reset
pulse may fight the driver's own init sequencing — see 2.1).

---

## 2. Display driver: migrate Seeed_GFX (v1) → Seeed_GFX2

### 2.1 Current state

`platformio.ini` uses `https://github.com/Seeed-Studio/Seeed_GFX.git` (v1,
a TFT_eSPI fork) with hand-edited `User_Setup.h` defines
(`GDEB0709E01_DRIVER`, `TFT_CS=44`, etc.) plus a compile-time `#error`
guard in `Gdeb0709e01Panel.cpp:17-19` because TFT_eSPI's CS selection
breaks on D-pin names.

Seeed's own README on the Seeed_GFX repo now says: **"Migrating to
Seeed_GFX2 — this library is Seeed's previous-generation graphics
library… We recommend choosing Seeed_GFX2"** (verified live 2026-10-07).

### 2.2 What GFX2 buys us (from Seeed's changelog)

- **Product-first configuration** — select the panel from a built-in
  catalog (`Seeed_Product::Seeed_ePaper_7INCH09_C`, which the earlier
  research confirmed explicitly lists the GDEB0709E01) instead of
  hand-editing `User_Setup.h`. The `#error` guard and the TFT_CS
  workaround disappear.
- **Packed 1/2/4-bit framebuffers for ePaper.** Today
  `drawPacked4bpp()` (`Gdeb0709e01Panel.cpp:57-84`) converts 4bpp →
  RGB565 in 64-row PSRAM bands and `pushImage()`s each band — ~3.8 MB
  pushed over SPI per full refresh, plus the band-buffer malloc/free.
  With a native 4bpp framebuffer the server bytes go straight to the
  driver: less SPI traffic, less code, no conversion bugs possible.
- **Layered Board → Bus → Driver → Panel architecture** — maps 1:1 onto
  this repo's `hal/Board` + `hal/Panel` seam. The `Panel` interface
  (`src/hal/Panel.h`) does not need to change.
- **`GfxResult` error returns** instead of silent failures (v1 `begin()`
  is void — the code works around it by polling BUSY, see lines 50-54).
- **Better watchdog behavior** during the ~30 s Spectra 6 refresh. The
  0.0.3 boot-loop backtrace landed in ESP-IDF power-management code;
  long blocking refreshes with Wi-Fi up are a known WDT risk area, and
  GFX2's refresh path is the maintained one.

### 2.3 Migration risk

Low-medium. `drawPacked4bpp`, `drawStatus`, QR, and `sleep()` keep their
signatures; only the driver calls inside change. The nibble→color mapping
(`Panel.h` `Spectra6` enum: White=0x0, Green=0x2, Red=0x6, Yellow=0xB,
Blue=0xD, Black=0xF) is panel-hardware truth, unaffected by the library
choice. Validate on hardware before release: GFX2's GDEB0709E01 support
is claimed in its catalog but has not been independently verified on a
physical panel by this project yet.

**Recommendation:** schedule the GFX2 migration as the next firmware
work item after the OTA MD5 fix. Keep the `hal/Panel` seam untouched.

---

## 3. Library replacement analysis (handwritten component by component)

| Component | Current | Verdict | Rationale |
|---|---|---|---|
| JSON parsing | `core/JsonLite` (~70 lines) | **KEEP** | Responses are server-controlled, flat, tiny (`ok`, `claim_code`, `status`, `device_token`). ArduinoJson (header-only, ~10 KB flash) buys nothing here and adds `JsonDocument` capacity-sizing pitfalls. See 3.1 for hardening notes. |
| URL template | `core/UrlTemplate` (~20 lines) | **KEEP** | Three token replacements. No library does this better. |
| HTTP client | Arduino `HTTPClient` | **KEEP** | Standard; used correctly (timeouts set, `collectHeaders` for ETag — the comment at `FrameFetcher.cpp:84-86` documents a real past bug). |
| Wi-Fi provisioning | `tzapu/WiFiManager@^2.0.17` | **KEEP** | Standard. |
| QR codes | `ricmoo/QRCode@^0.0.1` | **KEEP** | Tiny, correct. Stack buffer in `drawQRCode` (`Gdeb0709e01Panel.cpp:129`) is ~200-400 B for version 6 — fine. |
| Display driver | Seeed_GFX v1 | **MIGRATE → Seeed_GFX2** | See §2. |
| OTA flow | hand-rolled + `Update` | **KEEP structure, FIX §1.1** | Manifest format is custom; battery gate, staging, and progress UI justify the custom flow. Arduino `HTTPUpdate` can't do staged/manual-mode updates. |
| OTA manifest | custom key=value parser | **KEEP** | Custom format; parser is strict (rejects unknown keys, validates lengths/charsets — good). |
| NVS settings | `Preferences` | **KEEP** | Standard. The read-compare-write in `Config::savePendingUpdate` (`Config.cpp:119-155`) is good flash-wear practice. |
| Time/NTP | `configTime` + POSIX TZ | **KEEP** | `ezTime` etc. add a dependency for no gain. `TimeSync`'s `fetchIpApiOffset` correctly documents its HTTP-only tradeoff. |
| Battery curve | 12-point table | **KEEP** | Correct approach; matches server-side expectations. |
| Scheduler / QuietHours | pure-logic custom | **KEEP** | Tiny, unit-tested, correct (midnight wrap handled). |
| Button ISR timestamps | custom RTC_DATA_ATTR | **KEEP** | Neat solution for hold-gesture timing; correctly notes the deep-sleep-wake limitation. |
| Status badge | hand-rolled 5x7 font | **KEEP** | Niche requirement (badge composited into 4bpp buffer); no library fits better. `setPx` bounds-checks — good. |

### 3.1 JsonLite hardening (keep, but fix two fragilities)

`src/core/JsonLite.cpp`:

1. **`valuePos()` matches keys inside string values.** `body.find("\"key\"")`
   finds the first occurrence anywhere — e.g. searching for `"token"`
   would match inside `"device_token"`, and a key name appearing inside a
   *value* string would false-positive. The server responses are
   machine-generated and flat, so this is latent, not live. Cheap fix:
   after finding the quoted key, require the preceding char to be `{`,
   `,`, or whitespace.
2. **`registerDevice()` parses `expires_in` with `indexOf` hackery**
   (`DeviceClient.cpp:110-119`) instead of a `jsonInt()` helper. Add
   `long jsonInt(body, key, fallback)` to JsonLite for consistency; the
   current code works (lenient `toInt()` + 600 s fallback) but duplicates
   parsing logic.

Neither justifies pulling in ArduinoJson.

---

## 4. More findings (by severity)

### 4.1 `drawStatus` has no line-count guard
`Gdeb0709e01Panel.cpp:87-125` — text starts at y=300, advances 70 px/line
on a 1600 px panel. `numLines > ~18` runs off-screen. All current callers
pass ≤ 6 lines. Add `if (y > 1500) break;` — one line, prevents a future
long error message from drawing into the QR corner.

### 4.2 `drawSetupQR` ignores its `title` parameter
`Gdeb0709e01Panel.cpp:163-164` hardcodes `"FolioFrame Setup"` instead of
using `title`. Either use the parameter or drop it from the signature.

### 4.3 Pairing poll loop blocks button input for 10 s at a time
`src/main.cpp` `pairWithServer()`: `delay(10000)` between claim polls.
A user holding BTN1 during pairing gets no response until the next poll.
Acceptable for a pairing flow, but a `for` loop of 100×100 ms delays with
button polling would be friendlier. Low priority.

### 4.4 `FrameFetcher` rejects `Content-Length: -1` (chunked)
`FrameFetcher.cpp:100-104` requires `clen == bufSize_` exactly. If the
server ever sends chunked encoding, `getSize()` returns -1 and every
fetch fails closed ("refuse to paint garbage" — the right default, but
worth knowing the failure mode if the server stack changes).

### 4.5 OTA `Update.begin(total)` with no free-space check
`OtaManager.cpp:121` — fine on the 8 MB partition layout (2 OTA slots),
but a defensive `Update.begin` failure already returns "Update.begin
failed". Adequate.

### 4.6 `TimeSync::fetchIpApiOffset` integer division
`TimeSync.cpp:77` — `toInt() / 60`: offsets are multiples of 900 s, so
`/60` is always exact. The POSIX-sign inversion comment is correct.
No bug.

### 4.7 `EE02Board::usbPowered()` heuristic
`EE02Board.cpp:119-123` — `batteryMilliVolts() >= 4200` implies USB.
Documented as a heuristic ("Proper PMIC detection is a v2 item").
Consistent with `batteryPercent()` returning 100 at ≥4200 mV and the OTA
gate treating pct==0 as safe-to-flash. Coherent.

### 4.8 `Config::load()` re-validates and resets on corruption
`Config.cpp:88` — corrupt NVS → safe defaults. Good. The v1 URL-template
migration check (lines 80-84) is a nice touch.

### 4.9 `PowerManager::sleepUntilNext` clamps via Scheduler
`Scheduler.cpp` clamps to `[EE02_MIN_SLEEP_SEC, EE02_MAX_SLEEP_SEC]` and
re-clamps after quiet-hours extension. Overflow-safe (max ~691200 s).
Correct.

### 4.10 `main.cpp` reference re-assignment in the server-URL loop
`src/main.cpp` `while (!s.serverUrl[0])` loop does `s = config.get();`
where `s` is `Settings&`. This *copies* into the referenced struct
(valid C++, works), but it reads as re-seating a reference. Consider
`config.load();` then using `config.get().serverUrl[0]` directly for
clarity. Not a bug.

### 4.11 Stack pressure in `Portal::settingsPage()`
`Portal.cpp:118-165` builds the HTML with `String` concatenation (many
small heap allocs). The portal runs rarely and not concurrently with the
frame fetch, so fragmentation risk is acceptable. No change needed.

### 4.12 `OtaManager::getManifest` 404 handling
`OtaManager.cpp:74-77` — 404 returns false with *no* error set, and
`otaCheckError()` (`main.cpp`) distinguishes "no channel" from real
errors. Good design, correctly documented.

### 4.13 `DeviceClient::postJson` / `FrameFetcher` / `OtaManager` TLS
All three use `secure.setInsecure()` with comments citing the documented
tradeoff (`docs/SECURITY.md`: no maintained CA bundle on the device).
Deliberate, documented — not flagged as a bug.

---

## 5. What the code does well (keep these patterns)

- **HAL seam discipline** — `hal/Board` + `hal/Panel` are clean; no
  app-layer file touches GPIOs/ADC/sleep directly. New hardware = new
  subclass, as `AGENTS.md` promises.
- **`core/` is pure C++17 with no Arduino dependency** and is natively
  unit-tested (`tools/run_tests.sh`). `Scheduler`, `QuietHours`,
  `BatteryCurve`, `OtaManifest`, `Validate` are all correct on review.
- **NVS namespace separation** (`spectra` vs `spectra_dev`) so settings
  dumps never carry the device token. `Config::validate` is thorough.
- **Button wakeup re-armed in `EE02Board::deepSleep()` itself**, not just
  the PowerManager path — the comment documents the panic/battery/Wi-Fi
  failure paths. This is the kind of bug that only gets fixed after
  losing a device in the field; it's already fixed here.
- **ETag `collectHeaders()`** — the comment records a real past bug
  (every wake repainted without it).
- **Battery read before Wi-Fi** (ADC noise lesson) with 16-sample
  averaging and divider-enable gating.
- **Strict OTA manifest parsing** (unknown keys rejected, charset/length
  validated) — the right posture for something that triggers a flash.

---

## 6. Prioritized action items

| # | Item | File:line | Effort |
|---|---|---|---|
| 1 | **Fix `Update.setMD5` — pass hex string, check return** | `src/app/OtaManager.cpp:95-104` | 15 min |
| 2 | Remove magic GPIO numbers in panel `begin()` (or move to `board_config.h`) | `src/hal/Gdeb0709e01Panel.cpp:42-53` | 30 min |
| 3 | Migrate display driver Seeed_GFX → **Seeed_GFX2** (native 4bpp blit, drop User_Setup.h hacks, drop TFT_CS `#error` guard) | `platformio.ini`, `src/hal/Gdeb0709e01Panel.*` | half day + hardware validation |
| 4 | Harden `JsonLite::valuePos` (key-boundary check); add `jsonInt()` helper and use it for `expires_in` | `src/core/JsonLite.*`, `src/app/DeviceClient.cpp:110-119` | 1 hr |
| 5 | Guard `drawStatus` line count; use-or-drop `title` param in `drawSetupQR` | `src/hal/Gdeb0709e01Panel.cpp:87,163` | 20 min |
| 6 | Verify task-WDT is fed during the ~30 s `epaper.update()` (related to the 0.0.3 boot-loop signature) | `src/hal/Gdeb0709e01Panel.cpp:114-123` | investigation |
| 7 | Poll buttons during the 10 s pairing delay instead of `delay(10000)` | `src/main.cpp` (`pairWithServer`) | 30 min |

**Do NOT do:** replace JsonLite with ArduinoJson; replace UrlTemplate;
replace the OTA flow with HTTPUpdate; add on-device dithering; "fix" the
TLS tradeoff without reading `docs/SECURITY.md`.
