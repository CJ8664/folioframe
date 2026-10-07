#pragma once
// EinkTheme.h — Warm Clay design tokens mapped to GDEB0709E01 6-ink palette.
//
// The GDEB0709E01 panel has 6 inks. The Seeed_GFX driver's 4bpp sprite
// uses `color & 0x0F` as the palette index. Standard TFT_* constants
// produce WRONG inks (TFT_RED=0xF800 -> 0x0 -> BLACK). Use these raw
// nibble constants instead.
//
// Verified mapping (from driver source + hardware):
//   Nibble 0x0F -> WHITE (panel white)
//   Nibble 0x00 -> BLACK (panel black)
//   Nibble 0x0B -> YELLOW
//   Nibble 0x06 -> RED
//   Nibble 0x0D -> BLUE
//   Nibble 0x02 -> GREEN
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
static const uint16_t INK_WHITE  = 0x0F;  // panel white
static const uint16_t INK_BLACK  = 0x00;  // panel black
static const uint16_t INK_RED    = 0x06;  // clay/rust accents
static const uint16_t INK_YELLOW = 0x0B;  // ochre accents
static const uint16_t INK_BLUE   = 0x0D;  // blue accent
static const uint16_t INK_GREEN  = 0x02;  // sage accents

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
