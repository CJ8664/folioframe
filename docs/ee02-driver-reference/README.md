# EE02 / GDEB0709E01 driver reference for external review

Staged 2026-10-05. Purpose: the repo's `.pio/` build directory is gitignored,
so anyone cloning this repo cannot see the Seeed driver sources the firmware
builds against. This folder vendors the exact panel-driver files (unmodified)
so an external reviewer can compare the working and broken drivers without
running PlatformIO.

Library versions are pinned in the repo-root `platformio.ini`
(`[env:ee02]` uses Seeed_GFX v1, `[env:ee02_minimal]` uses Seeed_GFX2).

## Contents

- `seeed_gfx_v1/GDEB0709E01_Defines.h` — register defines + init macros for the
  7.09" panel. **This is where the dual-CS (CS0=GPIO44 / CS1=GPIO41) sequencing
  lives**: the macros assert/de-assert CS1 explicitly around the command
  stream. Read this first.
- `seeed_gfx_v1/GDEB0709E01_Init.h` — pin init, power-gate (GPIO43), reset pulse.
- `seeed_gfx_v1/GDEB0709E01_Rotation.h` — rotation handling.
- `seeed_gfx_v1/SPI_WRITE_PRIMITIVES.md` — `begin_tft_write`, `end_tft_write`,
  `writecommand`, `writedata`, `writecommanddata` extracted verbatim from
  `Seeed_GFX/TFT_eSPI.cpp`, with the CS/DC macro semantics. Key fact: `CS_L`/
  `CS_H` touch **TFT_CS (CS0) only**; CS1 is driven by the panel macros.
- `seeed_gfx_v2/Driver_GDEB0709E01.cpp` / `.h` — the Seeed_GFX2 (v2) driver for
  the same panel. v2's driver was cloned from the 13.3" T133A01 driver ~7 weeks
  ago with almost no real-world use; even the bare Seeed HelloWorld example
  through v2 fails to execute a panel refresh on this hardware.

## Corrected prompt snippet (replaces the .pio paths in the earlier prompt)

**Key files:**
- `TECHNICAL_REPORT_GDEB0709E01.md` — full findings, binary analysis, all 8 test results (read this first)
- `docs/ee02-driver-reference/seeed_gfx_v1/` — the WORKING v1 panel driver: init
  macros with the dual-CS sequencing (`GDEB0709E01_Defines.h`), pin/power/reset
  init (`GDEB0709E01_Init.h`), plus `SPI_WRITE_PRIMITIVES.md` (the exact
  `writecommand`/`writedata`/`begin_tft_write`/`end_tft_write` implementations —
  note `CS_L`/`CS_H` drive CS0/GPIO44 only; CS1/GPIO41 is toggled explicitly by
  the panel macros)
- `docs/ee02-driver-reference/seeed_gfx_v2/Driver_GDEB0709E01.cpp` — the BROKEN
  v2 driver to compare against
- `platformio.ini` — build configs, including `[env:ee02]` (7.09" v1 driver)
  and `[env:ee02_133test]` (13.3" driver test)
- `server/firmware/firmware-0.0.0.bin` through `firmware-0.0.6.bin` — all test binaries

**What I need:** Pinpoint the specific flaw in the v2 SPI driver
implementation relative to v1. The init register values are proven correct —
the bug is in *how* commands are sent. Focus on:
1. SPI clock speed and mode configuration
2. Exact command send order and timing delays between init commands
3. CS0/CS1 toggle sequence for dual-COG (when each is asserted, alone vs both)
   — in v1, `writecommand` toggles CS0 per byte while the panel macros hold
   CS1; check what v2 does differently
4. BUSY polling logic (polarity, timeout, where in the sequence it's checked)
5. PON (0x04) → DRF (0x12) → POF (0x02) sequence and CS handling for each
6. DTM (0x10) framebuffer transmission: chunk size, pacing, per-COG split

Don't give general advice. Identify the specific line(s) or sequence that
differ from the working v1 implementation and explain why they'd cause BUSY to
never return HIGH.
