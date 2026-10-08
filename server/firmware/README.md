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

`tools/package_firmware.sh ee02` copies the binaries here and writes `VERSION`
and `BUILD` from `FW_VERSION` and `FW_BUILD` in `src/main.cpp`. The
firmware GitHub Actions workflow packages these files and publishes
`firmware.bin`, `firmware-<version>.bin`, `VERSION`, and `BUILD` to a release
tagged `folioframe-v<version>`. The server downloads and validates those
release assets at startup or when an administrator selects **Check for
firmware updates** on `/flash`.

The `firmware` Docker volume is seeded from these files when first created.
Runtime refresh replaces only firmware binaries and version metadata; it
retains older versioned firmware and the bootloader/partition assets. No
server image rebuild or manual copy into the running container is required.

For local testing, package the current PlatformIO build into this directory.
The production version/build values continue to come from `src/main.cpp`.

- **Web flash** — the public `/flash` page (no login) offers the
  browser-based serial flasher. Anyone can flash a frame over USB and
  then point it at any SpectraFrame server in its Wi-Fi portal.
- **OTA** — devices whose `FW_BUILD` is lower than `BUILD` download
  `firmware.bin`, MD5-verify it, and flash it on next wake.

The `/flash` page hides itself until all four files exist. Nothing here
contains secrets — the firmware holds no credentials (Wi-Fi and the
server URL are entered on the device's own portal).
