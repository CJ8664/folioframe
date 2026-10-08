# FolioFrame Hardware Research — 2026-10-08

## Panel: Good Display GDEB0709E01 (7.09" Spectra 6)

### Physical
- Resolution: 1200 × 1600 pixels (portrait)
- Size: 7.09" diagonal
- Pixel pitch: ~0.09mm (calculated from 7.09" diagonal at 1200x1600)
- Interface: SPI (SCLK=GPIO7, MOSI=GPIO9, CS_M=GPIO44, CS_S=GPIO41, DC=GPIO10, BUSY=GPIO4, RST=GPIO38, EN=GPIO43)
- Connector: 60-pin 0.5mm FPC

### Spectra 6 Color System
- 6 native colors: Black (0xF), White (0x0), Red (0x6), Yellow (0xB), Blue (0xD), Green (0x2)
- 4-bit per pixel (nibble), 2 pixels per byte
- Framebuffer: 1200 × 1600 / 2 = 960,000 bytes (~937.5 KB)
- 60,000 color gamut via dithering (not native)
- Contrast ratio: 30:1
- No grayscale — only the 6 colors (plus dithering)

### Refresh Behavior
- Full refresh: **30-37 seconds** (measured on this exact panel via SenseCraft firmware; repo's hardware checklist says "~30s")
- Partial refresh: NOT supported on Spectra 6
- E Ink Sparkle/Ripple: waveform-level flicker effect during transitions (not full partial refresh)
- No backlight — reflective display
- **Dual-COG architecture**: two controllers, each driving 1200×800 (relevant for SPI-level simulation)

### Power
- Refresh power: <70mW (4" reference; 7.09" figure not sourced)
- Standby: <0.01mW (essentially zero — bistable)
- Operating voltage: 3.3V
- Bistable: holds image with zero power
- Controller: UC8179 family (per Panel.h comment)

### Temperature
- Operating: 0°C to 50°C
- Storage: -25°C to 60°C

## Board: Seeed EE02 (XIAO ESP32-S3 Plus)

### MCU
- ESP32-S3R8: dual-core Xtensa LX7 @ 240MHz
- 8MB octal PSRAM
- 16MB SPI flash
- WiFi 4 (2.4GHz) + Bluetooth 5.0 LE

### Pin Map (from board_config.h)
- KEY1 (Refresh): GPIO2
- KEY2 (Previous): GPIO3
- KEY3 (Next): GPIO5
- Battery ADC: GPIO1 (divider ratio 7.16, enable on GPIO6)
- Panel: SCLK=7, MOSI=9, CS_M=44, CS_S=41, DC=10, BUSY=4, RST=38, EN=43
- Status LED: none confirmed (-1 = disabled)
- Battery: JST PH 2.0mm, J3 pin 1 = +

### Power Management
- Deep sleep: 60s min, 7 days max
- Button wakeup armed on all paths
- OTA blocked below 40% battery
- USB-C for power/flashing

### Memory Constraints
- Framebuffer: 960KB (must fit in PSRAM — 8MB available, OK)
- Firmware: ~1.1MB (fits in 16MB flash with OTA dual partition)
- Band rendering: 64 rows × 1200px × 2B = 153.6KB working buffer

## Key Constraints for Simulator

1. **6-color palette only**: White #FFFFFF, Black #000000, Red, Yellow, Blue, Green (exact RGB values need calibration)
2. **1200×1600 portrait**: exact dimensions
3. **4bpp packed**: 2 pixels per byte, nibble order matters
4. **~15s refresh**: simulator should show refresh as instant but note the real timing
5. **No partial refresh**: full screen redraw every time
6. **Bistable**: simulator should persist last image
7. **Buttons**: 3 buttons (GPIO2/3/5) for UI navigation testing
8. **Battery**: ADC reading affects OTA gating and low-battery screens
