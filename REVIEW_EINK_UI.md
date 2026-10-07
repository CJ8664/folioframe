# E-Ink UI Gap Analysis: Mockups vs Firmware

**Date:** 2026-10-07
**Scope:** Bridge the FolioFrame e-ink setup/status UI to the approved Warm Clay mockups.
**User constraint:** Font family does NOT need to match — any simple font is fine. What must match: background colors, layout/positions, font-size hierarchy, QR positioning, spacing.

---

## 1. Mockup Design Language

### 1.1 Canonical Warm Clay tokens (from `spectraframe-ux-setup-portal`, canonical skin)

| Token | Hex | Usage |
|---|---|---|
| `--paper` / screen bg | `#f7f1e5` | Device screen background (pairing uses `#f7f1e5`) |
| `--ink` | `#2f302a` | Primary text (charcoal) |
| `--text` alt | `#23211C` / `#1c1a18` | Headings (pairing/setup variants) |
| `--muted` | `#69685d` | Secondary text, captions |
| `--muted` alt | `#6B655A` / `#5a554e` / `#625c54` | Body text variants |
| `--clay` | `#c1663e` | Primary accent (network card bg, blobs) |
| `--clay-deep` / `--rust` | `#9e4c2e` / `#A65A36` | Links, server URL, emphasis |
| `--rust-dark` | `#7b3528` | Topline, Wi-Fi icon, card border |
| `--ochre` | `#C99A3F` | Gold accents |
| `--ochre-deep` | `#9d6c20` / `#7a5016` | Step-number circles |
| `--sage` / `--sage-deep` | `#859879` / `#607457` | Secondary accent, labels |
| `--sage-wash` | `#dfe5d6` | Step-number circle bg, decorative |
| `--clay-wash` | `#ead1c1` | Decorative wash |
| `--line` / `--border` | `#d8cdbc` / `#c9c0b2` | Rules, dividers, card borders |
| `--qr-paper` | `#fffaf1` | QR code background |
| `--success` | `#3F6B4F` | Success states |

### 1.2 Screen A — Pairing (`spectraframe-ux-pairing/index.html`)

1200×1600 canvas (`.screen-1200`), bg `#f7f1e5`. Elements (absolute positions):

| # | Element | Position | Size | Color |
|---|---|---|---|---|
| 1 | "FolioFrame Setup" header + 74px logo mark | left:80, top:130 | 75px | `#2f302a` |
| 2 | "Pair this frame" title (centered) | center-x:600, top:300 | 75px | `#23211C` |
| 3 | Step 1 "Open your FolioFrame console in a browser" | top:480 | 39px | `#6B655A` |
| 4 | Step 2 "Go to 'Pair a frame'" | top:610 | 39px | `#6B655A` |
| 5 | Step 3 "Enter this code:" (left-aligned) | left:190, top:735 | 42px | `#69685d` |
| 6 | Claim code "A3B7-92KD" (centered) | top:860 | 48px | `#23211C` (alt: `#9e4c2e`) |
| 7 | Server URL (centered) | top:1020 | 48px | `#A65A36` (rust) |
| 8 | Help QR + "Scan for help" caption | right:76, bottom:64 | 296×296px QR, 28px caption `#69685d` | QR on `#fffaf1` |
| — | Backdrop blobs (decorative) | clay blob left:-420 top:410 (920×560); sage circle bottom-right; white circle top-right | — | `#c1663e` @.62, `#dfe5d6` @.9 |

Note: "?" hint buttons in the mockup are web-annotation chrome — omit on device.

### 1.3 Screen B — Wi-Fi Setup (`spectraframe-ux-setup-portal/index.html`)

1200×1600 canvas, bg `#f7f1e5`. Elements:

| # | Element | Position | Size | Color |
|---|---|---|---|---|
| 1 | Topline "FOLIOFRAME SETUP" + 74px mark | left:82, top:67 | 24px, ls .13em, uppercase | `#607457` (sage) |
| 2 | Screen count (e.g. "3") | right:82, top:75 | 23px | `#607457` |
| 3 | Title (e.g. "Connect to Wi-Fi") | left:80, top:130 | 75px | `#2f302a` |
| 4 | Intro paragraph | left:84, top:224 | 26px, lh 1.32 | `#69685d` |
| 5 | Rule | left:82, top:285, 1036×2px | — | `#d8cdbc` |
| 6 | Network card (AP name) | left:82, top:326, 1036×132px | 29px mono | bg `#c1663e`, text `#fff8ed` |
| 7 | Step 1 (numbered circle 58px) | top:505 | h2 30px `#2f302a`, p 21px `#69685d` | circle bg `#dfe5d6`, num `#607457` 27px |
| 8 | Step 2 | top:655 | same | same |
| 9 | Step 3 | top:806 | same | same |
| 10 | QR region: two labeled QR cards | left:82, top:1000, width:1036 | card 470px tall | card bg `#fffaf1` @.76, border 2px `#d8cdbc` |
| 11 | QR heading / label / image / URL | inside card | 27px / 16px / 248px / 15px mono | `#2f302a` / `#607457` / `#9e4c2e` |
| 12 | Footnote | left:82, bottom:45 | 18px | `#69685d` |

### 1.4 Other mockups

- `spectraframe-ux-flows/index.html` — device screens still use the OLD dark-green theme (`#00a000` bg). **Outdated; ignore for e-ink work.**
- `spectraframe-ux-paired-fetching`, `-ota`, `-error` — no 1200×1600 device-screen specs found; the generic status screens (OTA progress, errors, battery) should follow the same Warm Clay language: paper bg, ink text, rust/sage accents.

---

## 2. Current Firmware UI Capabilities

### 2.1 What exists today

`src/ui/StatusScreen.cpp` — 20 screens, all funnel into two panel primitives:
- `panel_->drawStatus(title, lines[], n)` — centered title + centered lines
- `panel_->drawSetupQR(title, apName, url)` — two side-by-side QRs + instructions

`src/hal/Gdeb0709e01Panel.cpp`:
- `drawStatus()`: white fill, title at y=300 centered (font 4), lines at 70px spacing (font 4), help QR bottom-right (164px + "Scan for help" caption). **No header, no colors, no layout.**
- `drawSetupQR()`: title at y=180, two 328px QRs side-by-side centered, captions, 4 instruction lines. Close-ish to mockup Screen B's QR region but missing everything above it.

### 2.2 Available drawing primitives

`EPaper : public TFT_eSprite` — full TFT_eSPI API:
- `fillRect/drawRect/drawRoundRect/fillRoundRect`, `drawCircle/fillCircle`, `drawLine`, `drawPixel`
- `drawString` with GLCD fonts 1/2/4/6/7/8 + `setTextSize(n)` integer scaling + `setTextDatum()` (TL/TC/TR/ML/MC/MR/BL/BC/BR)
- `loadFont()` smooth .vlw fonts (SMOOTH_FONT enabled in build flags) — from LittleFS or flash C array
- `setFreeFont()` Adafruit GFX fonts (LOAD_GFXFF enabled)
- QR: `ricmoo/QRCode` lib, `drawQRCode(text, x, y, size)` helper exists

GLCD font metrics (usable; comment in code says fonts 6/8 have rendering issues on this driver):
| Font | Height | With setTextSize | Use for |
|---|---|---|---|
| 2 | 16px | ×2=32, ×3=48 | captions 15–18px, footnotes |
| 4 | 26px | ×2=52, ×3=78 | body 21–42px, titles 75px |
| 6 | 48px | — | (rendering issues — avoid) |
| 8 | 75px | — | (rendering issues — avoid) |

Practical size mapping (mockup → firmware):
| Mockup | Firmware |
|---|---|
| 75px title | font 4, size 3 (=78px) |
| 48px code/URL | font 4, size 2 (=52px) |
| 39–42px steps | font 4, size 2 (=52px) or size 1 (=26px) — pick per screen |
| 26–34px body/h2 | font 4, size 1 (=26px) |
| 21–24px small body | font 2, size 1 (=16px) — slightly small; or font 4 (26px) |
| 15–18px captions | font 2, size 1 (=16px) |
| 27–31px numbers | font 4, size 1 (=26px) |

### 2.3 CRITICAL: color pipeline (verified in driver source)

4bpp sprite `drawPixel` takes **`color & 0x0F`** as the palette index (no RGB matching).
`COLOR_GET` in `GDEB0709E01_Defines.h` remaps sprite nibble → panel ink:

| Draw with (low nibble) | `COLOR_GET` → panel | Ink |
|---|---|---|
| `0x0F` (= `TFT_WHITE`) | `0x00` | White ✓ (empirically verified) |
| `0x00` (= `TFT_BLACK`) | `0x01` | Black ✓ (empirically verified) |
| `0x02` | `0x06` | Red |
| `0x0B` | `0x02` | Yellow |
| `0x0D` | `0x05` | Blue |
| `0x06` | `0x03` | Green |

**Do NOT use `TFT_RED`/`TFT_BLUE`/etc.** — `TFT_RED` (0xF800) has low nibble 0x0 → draws BLACK. `TFT_BLUE` (0x001F) → nibble 0xF → draws WHITE. Define ink constants:

```cpp
// Sprite-nibble inks for Seeed_GFX 4bpp EPaper on GDEB0709E01.
// Pass these as the "color" to fillRect/drawString/etc. The low nibble
// is the sprite palette index; COLOR_GET remaps to the panel ink.
static const uint16_t INK_WHITE  = 0x0F;  // panel white
static const uint16_t INK_BLACK  = 0x00;  // panel black
static const uint16_t INK_RED    = 0x02;  // panel red    (clay/rust accents)
static const uint16_t INK_YELLOW = 0x0B;  // panel yellow (ochre/gold accents)
static const uint16_t INK_BLUE   = 0x0D;  // panel blue
static const uint16_t INK_GREEN  = 0x06;  // panel green  (sage accents)
```

**Accent colors need hardware verification** — red/yellow/blue/green mappings come from the driver's `COLOR_GET`; white/black are empirically confirmed on the user's device. A test screen cycling the four accents should be shown once.

### 2.4 Warm Clay → Spectra 6 ink mapping

The panel cannot do muted tones, tints, or transparency. Mapping is semantic, not colorimetric:

| Warm Clay | Hex | Ink | Notes |
|---|---|---|---|
| Paper bg | `#f7f1e5` | WHITE | |
| Ink text | `#2f302a`/`#23211C`/`#1c1a18` | BLACK | |
| Muted text | `#69685d`/`#6B655A`/`#5a554e` | BLACK | No gray available; hierarchy carried by SIZE not shade |
| Clay/rust | `#c1663e`/`#9e4c2e`/`#A65A36`/`#7b3528` | RED | URLs, emphasis, network card bg |
| Ochre/gold | `#C99A3F`/`#9d6c20`/`#7a5016` | YELLOW | Step circles (alt: black ring + black number) |
| Sage | `#859879`/`#607457`/`#3F6B4F` | GREEN | Topline, labels, step numbers |
| Borders/rules | `#d8cdbc`/`#c9c0b2` | BLACK (1–2px) or omit | Hairlines → thin black or drop |
| QR paper | `#fffaf1` | WHITE | QR needs white quiet zone — native |
| Card bg | `#ece4d5`/`rgba(255,250,241,.76)` | WHITE | Tinted cards → white + ink border |
| Blobs/washes | `#c1663e`@.62, `#dfe5d6`, white@.58 | OMIT | Decorative transparency impossible; drop for clean look |

Since muted grays collapse to black, **typographic hierarchy must do the work**: title 78px black, body 26px black, captions 16px black — size and position carry the structure.

---

## 3. Gap Analysis Per Screen

### 3.1 Pairing screen (`showPairing`)

**Mockup has:** header w/ logo, centered title, 3 steps, claim code, rust URL, bottom-right QR, decorative blobs.
**Firmware has:** centered title + 7 centered lines, no header, no QR (except help QR), all black on white.

| Mockup element | Firmware today | Fix |
|---|---|---|
| "FolioFrame Setup" header, 75px, left:80 top:130 | Missing | Draw at (80,130) left-aligned, font4×3, BLACK. Logo mark: draw 74px rounded square w/ "F" or frame glyph in RED, or omit mark |
| "Pair this frame" 75px centered top:300 | Title drawn at y=300 centered, font4×1 (26px!) | Change to font4×3 (78px), BLACK |
| Steps 39px `#6B655A` at tops 480/610/735 | 26px centered lines | Left-align block at x=190–600, font4×2 (52px) BLACK; or centered font4×1 |
| Claim code 48px top:860 | 26px line | font4×2 (52px), BLACK (or RED for emphasis) |
| Server URL 48px rust top:1020 | 26px line | font4×2 (52px), RED |
| Help QR 296px right:76 bottom:64 | 164px QR exists | Enlarge to 296px at (1200-76-296, 1600-64-296-40); caption 16px below |
| Backdrop blobs | None | OMIT (no transparency) |

### 3.2 Wi-Fi setup screen (`showPortal` → `drawSetupQR`)

**Mockup has:** sage topline, count, 75px title, intro, rule, clay network card, 3 numbered steps, two labeled QR cards, footnote.
**Firmware has:** title, two QRs side-by-side, 4 instruction lines. Missing everything above the QRs.

| Mockup element | Firmware today | Fix |
|---|---|---|
| Topline 24px sage, left:82 top:67 | Missing | font2 (16px) GREEN, letter-spaced manually (drawString has no ls; insert spaces) |
| Title 75px left:80 top:130 | Title centered y=180, 26px | Left-align (80,130), font4×3, BLACK |
| Intro 26px + rule 2px | Missing | font4 (26px) BLACK; `fillRect(82,285,1036,3,INK_BLACK)` — or 2px |
| Network card 1036×132 clay | Missing | `fillRoundRect(82,326,1036,132,18,INK_RED)`; AP name 26px mono-ish WHITE centered |
| Steps with 58px numbered circles | Missing | `drawCircle` r=29 BLACK (or fillCircle GREEN w/ WHITE number); h2 font4 BLACK; p font2 BLACK |
| Two labeled QR cards | Two bare QRs exist | White card: `drawRoundRect` border BLACK 2px; label 16px GREEN uppercase; QR 248px; URL 16px RED below |
| Footnote 18px bottom:45 | Missing | font2 (16px) BLACK at y≈1520 |

### 3.3 Generic status screens (`drawStatus` — OTA, errors, battery, Wi-Fi)

Apply the same header pattern everywhere: **"FolioFrame Setup" 75px-equivalent header** (per AGENTS.md: common header across setup screens until pairing) or the screen title left-aligned at (80,130), body lines left-aligned at x=82, help QR bottom-right. This replaces the current centered-everything layout.

---

## 4. E-Paper UI Framework Research

**Finding: no Arduino/ESP32 "pretty UI" framework exists for Spectra 6.** What exists:

- **LVGL** (used by EKOS e-paper dashboard, jantielens ESP32 e-ink sample): full widget toolkit, but designed for interactive/touch UIs, large flash/RAM cost, and no Spectra-6 color palette support out of the box. Overkill for static status screens; would also need a display driver binding for the GDEB0709E01 (none exists — GxEPD2 doesn't support this panel).
- **TFT_eSPI smooth fonts (.vlw)**: antialiased TTF-derived fonts at any size via `loadFont()` (SMOOTH_FONT already enabled). Requires generating .vlw files (Processing sketch) and storing in LittleFS/flash. This is the one upgrade worth considering — it would get exact 75/48/39/27px sizes with smooth rendering. Cost: ~50–150KB flash per font size weight; needs hardware verification that EPaper sprite supports smooth fonts.
- **Everyone else hand-rolls**: ghostpaper, aitjcize/esp32-photoframe, EPF — all draw status screens with raw GFX primitives.

**Recommendation:** hand-roll with TFT_eSPI primitives (no new dependency). The screens are static compositions of rects/circles/text/QR — a ~300-line layout module. Optionally add one .vlw smooth font later for polish.

---

## 5. Concrete Implementation Plan

### 5.1 New module: `src/ui/EinkTheme.h` (~60 lines)

```cpp
#pragma once
// Warm Clay theme for 1200x1600 Spectra 6. See REVIEW_EINK_UI.md.
// Colors are sprite-nibble inks (low nibble of the uint16_t).
static const uint16_t INK_WHITE  = 0x0F;
static const uint16_t INK_BLACK  = 0x00;
static const uint16_t INK_RED    = 0x02;
static const uint16_t INK_YELLOW = 0x0B;
static const uint16_t INK_BLUE   = 0x0D;
static const uint16_t INK_GREEN  = 0x06;

struct TextStyle { uint8_t font; uint8_t size; uint16_t color; };
// Title 78px, Section 52px, Body 26px, Small 16px
```

### 5.2 New module: `src/ui/EinkLayout.cpp/h` (~250 lines)

Helpers built on the `Panel` seam (add methods to `Panel` or a wrapper):
- `header(const char* title)` — "FolioFrame Setup" 78px at (80,130) + optional logo
- `topline(const char* text)` — 16px GREEN uppercase at (82,67)
- `rule(y)` — 2px black line (82 → 1118)
- `stepNumber(x, y, n)` — 58px circle: `drawCircle` BLACK 3px + number 26px
- `qrCard(x, y, label, heading, qrText, url)` — bordered card + 248px QR + captions
- `networkCard(apName)` — red rounded rect + white AP name
- `bodyText(x, y, text, style)` — left-aligned text with datum handling

### 5.3 Rewrite `Gdeb0709e01Panel::drawStatus` / `drawSetupQR`

- `drawStatus`: paper-white bg → header → left-aligned title (80,130) → body lines at x=82 → help QR 296px bottom-right. Keep signature (callers unchanged).
- `drawSetupQR`: full Screen-B composition per table in §3.2.
- `showPairing` (StatusScreen.cpp): keep the 7-line content array but render with the new layout (header/title/steps/code/URL positions). Consider changing `drawStatus` signature to accept a layout struct, or add `drawPairing(claimCode, where)` to Panel.

### 5.4 Verification

1. **Ink test screen**: one firmware screen drawing swatches of all 6 inks with labels — photograph on device to confirm red/yellow/blue/green map correctly.
2. **Screenshot-compare**: render each screen, photograph device, side-by-side against mockup PNGs.
3. Existing `tools/stub_compile.sh` for host compile; `tools/run_tests.sh` unaffected (pure core/).

### 5.5 Effort estimate

| Item | LOC | Complexity |
|---|---|---|
| `EinkTheme.h` (inks, styles) | ~60 | Trivial |
| `EinkLayout` helpers | ~250 | Low — rects, circles, text |
| `drawStatus` rewrite | ~80 | Low |
| `drawSetupQR` rewrite | ~120 | Low–medium (QR card layout) |
| `showPairing` layout | ~40 | Low |
| Ink test screen | ~40 | Trivial |
| **Total** | **~600** | **2–4 days incl. hardware verification** |

No new libraries. No PROTOCOL.md changes. No server changes.

---

## 6. Feasibility Verdict

**Yes — the mockups can be matched closely** for layout, positions, sizes, colors (as 6-ink approximations), QR placement, and spacing. What cannot transfer:

1. **Muted warm tones** — everything collapses to 6 saturated inks; hierarchy moves from color-shade to size/position. This is the biggest visual difference and it's unavoidable on Spectra 6.
2. **Transparency/blobs/shadows** — omitted; the design still reads cleanly without them.
3. **Exact typefaces** — GLCD bitmap fonts; sizes match via multipliers. (Optional .vlw smooth-font upgrade later.)
4. **Fine hairlines** (`#d8cdbc` 2px rules) — become 2px black or are dropped.

The result will look like a high-contrast ink adaptation of the mockup — same information architecture, same positions, same size hierarchy, brand accents in red/green/yellow — not a pixel-perfect clone. That is the right target for e-paper.
