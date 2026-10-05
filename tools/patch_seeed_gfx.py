"""PlatformIO pre-build script: work around upstream Seeed_GFX2 incompatibilities
with Arduino-ESP32 2.0.x (ESP-IDF 4.4).

1. Bus_SPI_Platform.h calls `spi->begin(...)` expecting a bool return, but
   Arduino-ESP32 2.0.x `SPIClass::begin()` returns void.
2. The native ESP32-S3 LCD transports (Bus_ESP32QSPI / Bus_ESP32RGB) use
   ESP-IDF 5.x LCD APIs (`quad_mode` flag, new panel-IO signatures). They are
   unused by the Spectra 6 e-paper panel, so they are disabled below IDF 5.

Both patches are idempotent. Re-run `pio run` after a library update to
re-apply; remove this script once upstream fixes it.

Wired in platformio.ini via: extra_scripts = pre:tools/patch_seeed_gfx.py
"""
import os

Import("env")  # noqa: F821 -- provided by PlatformIO

MARKER = "Patched by tools/patch_seeed_gfx.py"

PATCHES = [
    (
        os.path.join("src", "bus", "Bus_SPI_Platform.h"),
        """    // Convert GPIO numbers to Arduino pin numbers before passing to begin()
    if (!spi->begin(seeed_gpio_to_arduino_pin(sclk),
                    seeed_gpio_to_arduino_pin(miso),
                    seeed_gpio_to_arduino_pin(mosi),
                    seeed_gpio_to_arduino_pin(cs))) {
      delete spi;
      return nullptr;
    }
    return spi;""",
        """    // Convert GPIO numbers to Arduino pin numbers before passing to begin()
    // %s: Arduino-ESP32 2.0.x SPIClass::begin() returns void, not bool.
    spi->begin(seeed_gpio_to_arduino_pin(sclk),
               seeed_gpio_to_arduino_pin(miso),
               seeed_gpio_to_arduino_pin(mosi),
               seeed_gpio_to_arduino_pin(cs));
    return spi;""" % MARKER,
    ),
    (
        os.path.join("src", "bus", "Bus_ESP32_LCD_Common.h"),
        """#if defined(ARDUINO_ARCH_ESP32) && defined(CONFIG_IDF_TARGET_ESP32S3)
#define SEEED_GFX_HAS_ESP32S3_LCD 1
#else
#define SEEED_GFX_HAS_ESP32S3_LCD 0
#endif""",
        """#include <esp_idf_version.h>
// %s: the native ESP32-S3 LCD transports (QSPI/RGB) need ESP-IDF 5.x
// LCD APIs; they are unused by the Spectra 6 e-paper panel, so disable
// them below IDF 5 (every use site already has an #else fallback).
#if defined(ARDUINO_ARCH_ESP32) && defined(CONFIG_IDF_TARGET_ESP32S3) && \\
    ESP_IDF_VERSION >= ESP_IDF_VERSION_VAL(5, 0, 0)
#define SEEED_GFX_HAS_ESP32S3_LCD 1
#else
#define SEEED_GFX_HAS_ESP32S3_LCD 0
#endif""" % MARKER,
    ),
]


def _patch():
    lib = os.path.join(
        env["PROJECT_DIR"], ".pio", "libdeps", env["PIOENV"], "Seeed_GFX2")
    if not os.path.isdir(lib):
        print("patch_seeed_gfx: library not downloaded yet, skipping")
        return
    for rel, old, new in PATCHES:
        path = os.path.join(lib, rel)
        with open(path) as f:
            src = f.read()
        if MARKER in src:
            print("patch_seeed_gfx: already patched " + rel)
            continue
        if old not in src:
            print("patch_seeed_gfx: WARNING: expected text not found in " +
                  rel + "; upstream may have fixed or changed the file")
            continue
        with open(path, "w") as f:
            f.write(src.replace(old, new))
        print("patch_seeed_gfx: patched " + rel)


_patch()
