# Firmware binaries

Four files live here (all from one `pio run` of the `ee02` env):

| File | Flash offset | Also used for |
|---|---|---|
| `bootloader.bin` | `0x0` | web flash only |
| `partitions.bin` | `0x8000` | web flash only |
| `boot_app0.bin` | `0xe000` | web flash only |
| `firmware.bin` | `0x10000` | web flash **and** OTA |

Where they come from after `pio run`:

- `.pio/build/ee02/bootloader.bin`
- `.pio/build/ee02/partitions.bin`
- `.pio/build/ee02/firmware.bin`
- `boot_app0.bin` lives in the Arduino-ESP32 package:
  `~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin`

Copy all four here, bump `"build"` (and `"fw_version"`) in the server
config, and redeploy. Then:

- **Web flash** — the public `/flash` page (no login) offers the
  esp-web-tools install button. Anyone can flash a frame over USB and
  then point it at any SpectraFrame server in its Wi-Fi portal.
- **OTA** — devices whose `FW_BUILD` is lower than `"build"` download
  `firmware.bin`, MD5-verify it, and flash it on next wake.

The `/flash` page hides itself until all four files exist. Nothing here
contains secrets — the firmware holds no credentials (Wi-Fi and the
server URL are entered on the device's own portal).
