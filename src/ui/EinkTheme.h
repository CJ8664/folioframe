#pragma once
// EinkTheme.h — Warm Clay design tokens mapped to GDEB0709E01 6-ink palette.
//
// The GDEB0709E01 panel has 6 inks. The Seeed_GFX driver's 4bpp sprite
// uses `color & 0x0F` as the palette index. Standard TFT_* constants
// produce WRONG inks (TFT_RED=0xF800 -> 0x0 -> BLACK). Use these raw
// nibble constants instead.
//
// Ink mapping — CALIBRATED FROM HARDWARE PHOTO (0.0.7, 2026-10-07).
//
// The 0.0.7 setup screen photo proves:
//   Nibble 0x0F -> DARK (was assumed white; photo shows dark background)
//   Nibble 0x00 -> LIGHT (was assumed black; photo shows light text)
//   Nibble 0x02 -> GREEN (network card drawn with 0x02 appeared green)
//
// Therefore:
//   WHITE (paper bg) must use 0x00
//   BLACK (text) must use 0x0F
//   GREEN (sage) is 0x02 (confirmed)
//   RED (clay/rust) reverted to 0x06 (original value; 0x02 is green, not red)
//   YELLOW/BLUE unchanged (0x0B, 0x0D) — still unverified, avoid for now
//
// Warm Clay mapping:
//   paper (#f7f1e5) -> WHITE
//   ink (#2f302a), muted (#69685d) -> BLACK (no gray exists; hierarchy via size)
//   clay (#c1663e), rust (#9e4c2e) -> RED
//   ochre (#C99A3F) -> YELLOW
//   sage (#607457) -> GREEN

#include <stdint.h>

namespace folioframe {
namespace theme {

// Raw nibble values for the 4bpp sprite (color & 0x0F)
static const uint16_t INK_WHITE  = 0x00;  // panel white (photo: 0x00 -> light)
static const uint16_t INK_BLACK  = 0x0F;  // panel black (photo: 0x0F -> dark)
static const uint16_t INK_RED    = 0x06;  // clay/rust accents
static const uint16_t INK_YELLOW = 0x0B;  // ochre accents
static const uint16_t INK_BLUE   = 0x0D;  // blue accent
static const uint16_t INK_GREEN  = 0x02;  // sage accents (photo: 0x02 -> green)

// Semantic aliases (Warm Clay design language)
static const uint16_t PAPER      = INK_WHITE;  // screen background
static const uint16_t INK        = INK_BLACK;  // primary text
static const uint16_t MUTED      = INK_BLACK;  // secondary text (no gray; use smaller size)
static const uint16_t CLAY       = INK_RED;    // primary accent
static const uint16_t RUST       = INK_RED;    // emphasis, links
static const uint16_t OCHRE      = INK_YELLOW; // gold accents
static const uint16_t SAGE       = INK_GREEN;  // secondary accent

// Display dimensions
static const int DISPLAY_W = 1200;
static const int DISPLAY_H = 1600;

// Font sizes (TFT_eSPI font 4 base = 26px at 1x)
//   font4 x3 = 78px (~75px titles)
//   font4 x2 = 52px (~48px claim code)
//   font4 x1 = 26px (body)
//   font2 x1 = 16px (captions)
static const int FONT_TITLE = 4;  // use with textSize 3
static const int FONT_BODY  = 4;  // use with textSize 1
static const int FONT_SMALL = 2;  // use with textSize 1

}  // namespace theme
}  // namespace folioframe
