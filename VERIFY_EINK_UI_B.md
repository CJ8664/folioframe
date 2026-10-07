# E-Ink UI Plan Verification — Second Reviewer (Technical Feasibility & Risks)

**Date:** 2026-10-07
**Scope:** Technical verification of `REVIEW_EINK_UI.md`. Focused on feasibility and risks, not re-measuring mockup coordinates.

**Verdict: The plan is technically sound.** Every load-bearing claim was verified against actual library/driver source. Two issues found (one minor, one latent bug worth fixing during the rewrite). Details below.

---

## 1. Color Pipeline — VERIFIED

The plan's critical claim — that standard TFT color constants produce wrong inks and raw nibble constants are required — is **correct**. Verified in actual source:

**Sprite nibble extraction** (`Seeed_GFX/Extensions/Sprite.cpp:1706`):
```cpp
uint8_t c = color & 0x0F;  // 4bpp sprite: low nibble only
```

**Text path**: `drawChar` → `drawPixel(x, y, color)` (Sprite.cpp:2087, 2090). `drawString` funnels through here. Confirmed.

**Panel remap** (`Seeed_GFX/TFT_Drivers/GDEB0709E01_Defines.h:253-261`):
```c
#define COLOR_GET(color) ( \
    (color) == 0x0F ? 0x00 : \   // sprite 0x0F -> panel white
    (color) == 0x00 ? 0x01 : \   // sprite 0x00 -> panel black
    (color) == 0x02 ? 0x06 : \   // sprite 0x02 -> panel red
    (color) == 0x0B ? 0x02 : \   // sprite 0x0B -> panel yellow
    (color) == 0x0D ? 0x05 : \   // sprite 0x0D -> panel blue
    (color) == 0x06 ? 0x03 : \   // sprite 0x06 -> panel green
    0x01 \                        // default -> black
)
```

**Worked example** (why TFT_RED is broken):
- `TFT_RED` = 0xF800 → `0xF800 & 0x0F` = 0x00 → sprite nibble 0x00 → `COLOR_GET` → 0x01 → **panel black** (not red)
- `TFT_BLUE` = 0x001F → `0x001F & 0x0F` = 0x0F → sprite nibble 0x0F → `COLOR_GET` → 0x00 → **panel white** (not blue)
- `TFT_WHITE` = 0xFFFF → 0x0F → 0x00 → white ✓ (works today, empirically confirmed)
- `TFT_BLACK` = 0x0000 → 0x00 → 0x01 → black ✓ (works today, empirically confirmed)

**The plan's `INK_*` constants are correct.** Using raw nibbles (0x0F/0x00/0x02/0x0B/0x0D/0x06) is not just sufficient — it's the *only* way to get accent colors through this pipeline. There is no other mangling point: `fillRect` on the sprite funnels through the same `drawPixel`.

**One nuance for readers:** the firmware has *two* nibble mappings that must not be confused:
- **UI path** (drawString/fillRect): sprite codes (0x0F=white, 0x00=black, 0x02=red…) → `COLOR_GET` → panel
- **Photo path** (`drawPacked4bpp`): server sends panel-native codes (0x0=white, 0xF=black, 0x6=red…) → `nibbleToRgb565()` → `pushImage` → sprite → panel

The plan correctly targets only the UI path. The photo path is out of scope here.

---

## 2. Font Availability — VERIFIED

**Build flags** (`platformio.ini`): `LOAD_GLCD`, `LOAD_FONT2`, `LOAD_FONT4`, `LOAD_FONT6`, `LOAD_FONT7`, `LOAD_FONT8`, `LOAD_GFXFF`, `SMOOTH_FONT` — all defined.

**Standard TFT_eSPI GLCD metrics** (fonts 2 and 4 are used in current code and visibly work):
| Mockup size | Firmware equivalent | Delta |
|---|---|---|
| 75px title | font 4, `setTextSize(3)` = 78px | +4% (imperceptible) |
| 48px code/URL | font 4, `setTextSize(2)` = 52px | +8% (imperceptible) |
| 39–42px steps | font 4, size 2 (52px) or size 1 (26px) | pick per screen |
| 26px body | font 4, size 1 = 26px | exact |
| 16–18px captions | font 2, size 1 = 16px | exact |

**Fonts 6/8 rendering issues:** stated in code comments (`Gdeb0709e01Panel.cpp`: "fonts 6/8 have rendering issues on this driver"). Root cause not identified in library source, but the code comment is authoritative and the plan correctly avoids them. `setTextSize` integer scaling on fonts 2/4 is the right workaround.

**SMOOTH_FONT** is enabled but unused — the plan correctly lists `.vlw` fonts as an optional later upgrade, not a requirement.

**The size hierarchy is achievable.** No blocker.

---

## 3. QR Code Rendering — VERIFIED (one latent bug flagged)

- **Library:** `ricmoo/QRCode@^0.0.1` (`platformio.ini:15`) — confirmed.
- **Positioning:** `drawQRCode(text, x, y, size)` takes absolute x/y (`Gdeb0709e01Panel.cpp:127`). The plan's coordinates (e.g., x=828, y=1600-64-296-caption for the 296px help QR) are directly implementable.
- **Colors:** QR uses `fillRect` with `TFT_WHITE` (background) and `TFT_BLACK` (modules) — both map correctly through the verified pipeline. White quiet zone is native. No change needed.

**⚠️ Latent bug (minor, pre-existing):** QR version is hardcoded to 6 (41 modules) in `drawQRCode`. Version 6 at ECC 0 holds ~106 alphanumeric characters. The GitHub URL (39 chars) fits, but a long portal URL with query parameters could overflow, and `qrcode_initText` failure is unchecked. **Recommendation:** while rewriting `drawSetupQR`, check the return value or compute the minimum version for the URL length. Not a plan-blocker, but the rewrite is the right time to fix it.

---

## 4. Layout Helpers — Assessment

**`EinkTheme.h` (ink constants): ESSENTIAL, not optional.** The raw nibble values must live in exactly one place. Today's code gets away with `TFT_WHITE`/`TFT_BLACK` only because those two happen to map correctly. Any accent-color work is impossible without the constants.

**`EinkLayout` helpers: the right abstraction, with one correction.**

The plan says "add methods to `Panel` or a wrapper." **It must be a wrapper — do not modify `Panel.h`.** Per `AGENTS.md`, `Panel` is a clean HAL seam ("New hardware = new subclass, nothing else changes"). Adding UI layout methods would pollute it and force every future panel subclass to implement them. Create a standalone `EinkLayout` class (or free functions) that draws via the existing `Panel`/`EPaper` public API.

**Is there a simpler approach?** Hardcoding coordinates directly in `drawStatus`/`drawSetupQR` would save ~100 lines but duplicate the header/QR/footer positioning across every screen. With 20 callers of `drawStatus`, the helper pays for itself on the second screen. The plan's approach is correct.

**Signature stability:** the plan keeps `drawStatus(title, lines[], n)` and `drawSetupQR(title, apName, url)` signatures unchanged — zero changes needed in `StatusScreen.cpp`. This is the right call; it localizes the rewrite to the HAL implementation.

---

## 5. Risk Assessment

### Biggest risk: accent colors unverified on hardware

`COLOR_GET` is in the driver source, so the mapping *should* hold. But white/black are the only inks ever drawn via the UI path on this device (confirmed by the user's photo). Red/yellow/blue/green have never been exercised through `drawString`/`fillRect` → sprite → `COLOR_GET` → panel on real hardware.

**If the mapping is wrong**, every accent in the redesigned UI (red network card, green topline, yellow step circles) renders as the wrong ink — a highly visible failure.

**Mitigation (already in the plan, §5.4.1):** build the 40-line ink test screen **first**, before any layout code. Photograph it on device. If accents are wrong, the color table gets corrected before a single mockup pixel is drawn. This sequencing is the most important detail in the plan — do not write layout code before the test screen passes.

### Second risk: scope of the `drawSetupQR` rewrite

Screen B (Wi-Fi setup) goes from "title + 2 QRs + 4 lines" to a full composition: topline, title, intro, rule, network card, 3 numbered steps, 2 labeled QR cards, footnote. That's not a tweak — it's ~120 lines of new layout code with ~15 positioned elements. The per-element table in §3.2 is the right spec, but expect one iteration of "photograph → nudge coordinates" per screen. Budget for it.

### What I would do differently

1. **Ink test screen before anything else.** (Plan has it as §5.4.1 — I'd promote it to step zero and gate all layout work on it.)
2. **Do not touch `Panel.h`.** Wrapper class only. (Plan allows both; I'm firm: wrapper.)
3. **Fix the QR version hardcoding** during the `drawSetupQR` rewrite (see §3 above).
4. **Defer the "FolioFrame Setup" header on *every* `drawStatus` caller** until the pairing/setup screens are verified. The 20 generic status screens (OTA, battery, errors) work fine today with centered text; restyling all of them in one shot increases blast radius. Do pairing + Wi-Fi setup first, verify on hardware, then roll the header pattern out to the rest.

### Non-risks (things I checked that are fine)

- **No PROTOCOL.md impact:** UI drawing is firmware-local; no wire-format changes.
- **No server changes:** confirmed.
- **Memory:** layout helpers are code, not buffers. The 960KB framebuffer is untouched. No PSRAM concern.
- **`tools/stub_compile.sh`:** layout code uses only `Panel`/Arduino APIs; host-compilable.
- **LVGL rejection:** correct. No Spectra 6 driver binding exists, and static screens don't need a widget toolkit.

---

## Conclusion

The plan is **technically sound and implementable as written**, with three adjustments: (1) wrapper class, not `Panel.h` methods; (2) ink test screen gates all layout work; (3) fix QR version hardcoding during the rewrite. The color pipeline — the plan's riskiest claim — was verified instruction-by-instruction against the actual Seeed_GFX v1 source. The 2–4 day estimate is realistic assuming one hardware photo-iteration per screen.
