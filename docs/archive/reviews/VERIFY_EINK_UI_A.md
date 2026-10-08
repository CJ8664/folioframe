# Verification: E-Ink UI Plan (REVIEW_EINK_UI.md)

**Verifier:** Independent subagent (adversarial review)  
**Date:** 2026-10-07  
**Scope:** All 5 claims in the e-ink UI gap analysis

---

## Claim 1: Mockup measurements accurate — ISSUE FOUND (partial)

Checked `spectraframe-ux-pairing/index.html` CSS against the review's table:

| Element | Review claimed | Actual CSS | Verdict |
|---|---|---|---|
| Header "FolioFrame Setup" | left:80, top:130, 75px | `left: 80px; top: 130px; font-size: 75px` | ✅ VERIFIED |
| Title "Pair this frame" | top:300, 75px | `.pair-title { top: 300px; font-size: 75px; }` | ✅ VERIFIED |
| Step 1 | top:480, 39px | `.open-console { top: 460px; font-size: 48px; }` left:190px | ❌ WRONG — 20px off, 9px size off |
| Step 2 | top:610, 39px | `.pair-menu { top: 660px; font-size: 48px; }` | ❌ WRONG — 50px off, 9px size off |
| Step 3 | left:190, top:735, 42px | `.code-prompt { top: 760px; font-size: 48px; }` | ❌ WRONG — 25px off, 6px size off |
| Claim code | top:860, 48px | `.claim-code { top: 860px; font-size: 48px; }` | ✅ VERIFIED |
| Server URL | top:1020, 48px rust | `.server-url { top: 1020px; font-size: 48px; }` | ✅ VERIFIED |
| Help QR | right:76, bottom:64, 296px | `right: 76px; bottom: 64px; width: 296px; height: 296px` | ✅ VERIFIED |

**Impact:** The step positions/sizes in the implementation plan (§3.1, §5.3) are based on wrong numbers. If implemented as specified, steps would be mispositioned by 20-50px and undersized. The plan needs correction before implementation.

**Also note:** The review's §1.2 says steps are `#6B655A` (muted) at 39px, but actual CSS shows 48px. The color may also be wrong — didn't verify.

---

## Claim 2: Critical color bug (COLOR_GET) — ISSUE FOUND (fabricated detail, correct conclusion)

**What the review claimed:** "4bpp sprite `drawPixel` takes `color & 0x0F` as the palette index (no RGB matching). `COLOR_GET` in `GDEB0709E01_Defines.h` remaps sprite nibble → panel ink" with a specific 6-row mapping table.

**What I found:**
- `COLOR_GET` **does not exist** in the codebase. Searched `src/` and `lib/` — zero hits. The file `GDEB0709E01_Defines.h` does not exist.
- The review claimed this was "verified in driver source" — it was not.

**What IS true:**
- `src/hal/Gdeb0709e01Panel.cpp:19-34` has `nibbleToRgb565()` which maps sprite nibble → RGB565:
  - `0x0` → white (0xFFFF)
  - `0x2` → green (0x07E0)
  - `0x6` → red (0xF800)
  - `0xB` → yellow (0xFFE0)
  - `0xD` → blue (0x001F)
  - `0xF` → black (0x0000)
- The sprite is 4bpp; `drawPixel`/`fillRect`/etc. with a `uint16_t color` will use the low nibble as the palette index (standard TFT_eSPI sprite behavior for 4bpp).
- Therefore: `TFT_RED` (0xF800, low nibble 0x0) → white. `TFT_BLUE` (0x001F, low nibble 0xF) → black. **The review's conclusion (don't use TFT_* constants) is CORRECT.**
- But the review's specific "panel ink" mappings (e.g., "0x0F → panel 0x00 → White") are **unsubstantiated**. The actual panel-side mapping happens inside the Seeed_GFX library (closed or in lib/), not in our code. The review invented `COLOR_GET` and its values.

**Corrected ink constants (based on `nibbleToRgb565`, sprite-side):**
```cpp
// Sprite nibble → displayed color (via nibbleToRgb565 + Seeed_GFX panel mapping)
static const uint16_t INK_WHITE  = 0x00;  // nibble 0x0 → white
static const uint16_t INK_BLACK  = 0x0F;  // nibble 0xF → black
static const uint16_t INK_RED    = 0x06;  // nibble 0x6 → red
static const uint16_t INK_YELLOW = 0x0B;  // nibble 0xB → yellow
static const uint16_t INK_BLUE   = 0x0D;  // nibble 0xD → blue
static const uint16_t INK_GREEN  = 0x02;  // nibble 0x2 → green
```

**Note:** This is the INVERSE of what the review specified (review said `INK_WHITE = 0x0F`, `INK_BLACK = 0x00`). The review's constants would draw **inverted** (white→black, black→white). This is a critical error — implementing the review's constants as-is would produce a black background with white text instead of the intended Warm Clay light theme.

**However:** The mapping from sprite RGB565 → actual e-ink panel color happens in the Seeed_GFX library. I did not verify that `nibbleToRgb565`'s "red" (0xF800) actually produces red ink on the physical panel. The review's claim that "white/black are empirically confirmed on the user's device" is plausible (the current firmware draws white bg/black text and the user's photos show this working). The four accent colors (red/yellow/blue/green) **do need hardware verification** — the review is correct about this, even if the mechanism description was wrong.

---

## Claim 3: Warm Clay → 6-ink mapping sensible — VERIFIED

The semantic mapping (paper→white, ink→black, clay/rust→red, ochre→yellow, sage→green) is reasonable given the 6-color constraint. Alternatives:
- Could map muted grays to dithered patterns, but solid black with size hierarchy is cleaner and the review's approach is correct.
- Could map clay/rust to yellow instead of red, but red is closer to `#c1663e` (terracotta) than yellow is. Review's choice is defensible.

No issues.

---

## Claim 4: No Arduino UI framework; hand-roll ~600 LOC / 2-4 days — VERIFIED (framework), ISSUE FOUND (estimate)

**Framework:** Web search for "Arduino ESP32 e-paper UI framework Spectra 6" returned firmware projects, drivers, and hardware — no UI widget frameworks. LVGL exists but is touch/interactive-focused with no GDEB0709E01 driver. The review's conclusion (hand-roll with TFT_eSPI primitives) is correct.

**Effort estimate:** The ~600 LOC / 2-4 day estimate is **optimistic**:
- The plan lists 6 items totaling ~590 LOC, but this doesn't account for:
  - QR code positioning math (centering, quiet zones)
  - Text datum handling for left/center/right alignment
  - The `drawSetupQR` rewrite involves 12 sub-elements (topline, title, intro, rule, network card, 3 steps with circles, 2 QR cards, footnote) — 120 LOC is tight
  - Hardware verification iterations (photograph → compare → adjust → reflash → repeat)
  - The step measurement errors (Claim 1) will cause rework
- **More realistic:** 800-1000 LOC, 1-2 weeks including 2-3 hardware verification cycles.

---

## Claim 5: Layout can match mockups closely — VERIFIED (with caveats)

Positions, sizes, and QR placement are achievable with TFT_eSPI primitives. The review's "high-contrast ink adaptation" framing is honest and correct — it won't be a pixel clone, but the information architecture will match.

**Caveat:** The implementation must use the **corrected** step positions from Claim 1, not the review's numbers.

---

## Summary

| Claim | Verdict |
|---|---|
| 1. Mockup measurements | **ISSUE FOUND** — Step positions/sizes wrong (20-50px, 6-9px off) |
| 2. Color bug (COLOR_GET) | **ISSUE FOUND** — `COLOR_GET` fabricated; ink constants inverted (would produce black bg) |
| 3. Warm Clay → ink mapping | **VERIFIED** — Sensible semantic mapping |
| 4. No framework; hand-roll | **VERIFIED** (framework) / **ISSUE FOUND** (estimate optimistic) |
| 5. Layout can match | **VERIFIED** — With corrected measurements |

## Critical Action Items Before Implementation

1. **Fix ink constants** — Use `INK_WHITE = 0x00`, `INK_BLACK = 0x0F` (not the review's inverted values). Verify accent colors on hardware before finalizing.
2. **Fix step measurements** — Use actual CSS values: steps at tops 460/660/760, 48px, left:190px (not 480/610/735, 39px).
3. **Revise effort estimate** — Plan for 1-2 weeks, not 2-4 days.
4. **Remove `COLOR_GET` references** — The mechanism doesn't exist; document the actual `nibbleToRgb565` path instead.
