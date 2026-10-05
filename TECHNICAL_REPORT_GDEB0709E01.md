# GDEB0709E01 7.09" Spectra 6 Driver Issue - Technical Report

## Hardware
- **Board:** Seeed XIAO ESP32-S3 Plus on EE02 carrier board
- **Panel:** Good Display GDEB0709E01 7.09" Spectra 6 e-paper, 1200×1600
- **Panel markings:** YS4709US031 / SPR0HG1 / B0EG6F02WJ / 24116-01390
- **Pin mapping:**
  - SCLK GPIO7, MOSI GPIO9, CS0 GPIO44, CS1 GPIO41
  - DC GPIO10, BUSY GPIO4, RST GPIO38, ENABLE GPIO43

## Symptom
`display.update()` / `epaper.update()` never completes. The BUSY pin behavior varies:
- Seeed_GFX2: BUSY never goes LOW (panel never starts refresh), `update()` returns after ~3s
- Seeed_GFX v1: `update()` hangs indefinitely (BUSY never returns HIGH)
- Custom bare-metal SPI driver: BUSY goes LOW (refresh starts) but never returns HIGH (90s+ timeout)

No image ever appears on the panel.

## What Works
1. **SenseCraft HMI firmware v1.2.2** (`EE02_7_09_color_1.2.2`): Drives the panel perfectly. Welcome screen renders with crisp colors. Boot log shows:
   ```
   [Board] ePaper display initialization succeed
   [app_view] Startup UI display update begin: combo=518, size=1200x1600
   [app_view] Display update completed in 37416u ms
   ```
   Full refresh takes 37.4 seconds. This proves hardware (board, cable, panel) is 100% functional.

2. **SenseCraft 13.3" firmware** (`EE02_13_3_color_1.1.2`): ALSO works on this 7.09" panel. This proves the 13.3" init sequence is compatible with the 7.09" hardware.

## What Fails (All Tests)

| Version | Driver | Result |
|---------|--------|--------|
| 0.0.0 | Seeed_GFX2 unpatched (`Seeed_ePaper_7INCH09_C`) | `update()` returns after 3s, BUSY never LOW |
| 0.0.1 v1-v7 | Custom bare-metal SPI driver | BUSY LOW (starts), 90s timeout (never finishes) |
| 0.0.1 v9 | Custom driver with Seeed values | BUSY LOW, 90s timeout |
| 0.0.2 | Seeed_GFX2 patched (F7, E8 28, C0...) | Same as 0.0.0, 3s timeout |
| 0.0.3 | Official HelloWorld example (unmodified) | Same as 0.0.0 |
| 0.0.4 | Seeed_GFX v1, fixed 1200×1600 framebuffer, WRONG TRES (1200×1600) | Hangs on `update()` |
| 0.0.5 | Seeed_GFX v1, 13.3" T133A01 driver | Hangs on `update()` |
| 0.0.6 | Seeed_GFX v1, correct TRES (1200×800 per-COG), Seeed values | Hangs on `update()` |

## Binary Analysis: SenseCraft Firmware

Downloaded `EE02_7_09_color_1.2.2-3deac219/firmware.bin` (3.6MB, ESP32-S3 IDF app) and extracted the e-paper init values from offset 0x1FE29D:

### Init Values (from working firmware)
- **AN_TM (0x74):** `00 0C 0C D9 DD DD 15 15 55` (9 bytes)
- **BTST_P (0x06) / BTST_N (0x05):** `E0 20` (2 bytes each)
- **TRES (0x61):** `04 B0 03 20` = **1200×800** (4 bytes)
- **CDI (0x50):** `0x37` (1 byte)
- **PWR (0x01):** `0F 00 28 2C 28 38...` (6+ bytes)

### Critical Findings
1. **TRES is per-COG, not full panel.** The 7.09" panel is dual-COG (two controllers). Each COG drives 1200×800 (half the 1600 height). TRES must be `04 B0 03 20` (1200×800), NOT `04 B0 06 40` (1200×1600).

2. **Seeed values are correct, guysie values are wrong.** The `philippwaller/esphome-epaper-spectra6-133` driver (vendored by guysie) uses:
   - CDI=`F7`, BTST=`E8 28`, AN_TM=`C0 1C 1C CC CC CC 15 15 55`
   - These are for Good Display's ESP32-133C02 board, NOT the EE02.
   - SenseCraft uses: CDI=`0x37`, BTST=`E0 20`, AN_TM=`00 0C 0C D9 DD DD 15 15 55`
   - The unmodified Seeed_GFX v1 driver has the CORRECT values.

3. **Values are not the problem.** Test 0.0.6 used byte-for-byte identical values to SenseCraft's firmware, with correct per-COG TRES. It still hung. The issue is in the driver implementation (SPI timing, CS sequencing, BUSY polling, power-up order), not the register values.

## The guysie Driver Confusion

The `guysie/random-things` repo contains a working Spectra 6 driver, but it is for Good Display's **ESP32-133C02** driver board, not Seeed's EE02. Key differences:
- No DC pin (uses ESP-IDF SPI command phase instead)
- Different init values (F7, E8 28, C0...) validated only on Good Display's 5V carrier
- Different hardware, different values — do NOT use for EE02

## Open Questions for Seeed
1. Has the 7.09" GDEB0709E01 driver in Seeed_GFX2 ever been tested on real EE02 hardware? There are zero GitHub issues.
2. What is the exact SPI transaction sequence (command order, timing delays, CS toggling) used by SenseCraft's firmware?
3. Why does the open-source 13.3" T133A01 driver hang when SenseCraft's 13.3" firmware works on the same 7.09" panel?
4. Can you share the actual e-paper driver source code from SenseCraft firmware, or the correct init sequence with timing?

## Test Logs

### 0.0.6 (correct values, still hangs)
```
=== Test 0.0.6: Correct TRES (1200x800 per-COG) ===
EPD 1200x1600, TRES 1200x800 per-COG
Begin OK
Calling update...
(stuck here, never returns)
```

### 0.0.5 (13.3" driver, hangs)
```
=== Test 0.0.5: 13.3in T133A01 driver on 7.09in panel ===
EPD 1600x1200
Begin OK
Calling update...
(stuck here, never returns)
```

### SenseCraft v1.2.2 (works)
```
[Board] ePaper display initialization succeed
[app_view] Startup UI display update begin: combo=518, size=1200x1600
[app_view] Display update completed in 37416u ms
```

## Conclusion
The hardware is functional. The init register values in the open-source drivers are correct (verified against SenseCraft's binary). The failure is in the driver implementation — specifically how commands are sequenced, timed, and transmitted via SPI. The open-source drivers do not replicate SenseCraft's actual behavior, even with identical register values.
