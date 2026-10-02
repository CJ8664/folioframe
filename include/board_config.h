#pragma once
// Single place for EE02 board-level pin map and defaults.
// Panel FPC signals (SCLK=7, MOSI=9, CS_M=44, CS_S=41, DC=10, BUSY=4,
// RST=38, EN=43) are owned by the Seeed_GFX2 product catalog — do NOT
// redefine them here.

// --- User buttons (from EE02 schematic; sven97/paperframe) ---
#define EE02_KEY1_PIN 2
#define EE02_KEY2_PIN 3
#define EE02_KEY3_PIN 5

// --- Battery (J3: pin 1 = +, pin 2 = GND) ---
// ADC pin / divider enable below come from the EE04 reference circuit
// (josomm22/seeed_eink_board). VERIFY against the EE02 schematic and a
// multimeter before trusting readings — see docs/HARDWARE_CHECKLIST.md.
#define EE02_BAT_ADC_PIN 1
#define EE02_BAT_EN_PIN 6
#define EE02_BAT_DIVIDER_RATIO 7.16f

// --- Status LED ---
// No GPIO status LED pin is confirmed for EE02; the green LED on the
// board is the charger indicator. -1 = disabled (blinkLed() no-ops).
#define EE02_STATUS_LED_PIN -1
#define EE02_STATUS_LED_ACTIVE_LOW true

// --- Deep sleep ---
#define EE02_MIN_SLEEP_SEC 60
#define EE02_MAX_SLEEP_SEC (7 * 24 * 3600)

// --- Panel ---
#define EE02_PANEL_WIDTH 1200
#define EE02_PANEL_HEIGHT 1600
// Packed 4bpp: 2 px/byte
#define EE02_FRAME_BYTES (EE02_PANEL_WIDTH * EE02_PANEL_HEIGHT / 2)

// --- OTA safety ---
#define EE02_OTA_MIN_BATTERY_PCT 40
