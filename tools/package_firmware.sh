#!/bin/bash
# Package ESP32 firmware binaries for the /flash web flasher + OTA.
#
# Usage: tools/package_firmware.sh [env]
#   env defaults to ee02. Run from the repo root after `pio run -e <env>`.
#
# Copies the four web-flash parts into server/firmware/:
#   bootloader.bin  @ 0x0      <- .pio/build/<env>/bootloader.bin
#   partitions.bin  @ 0x8000   <- .pio/build/<env>/partitions.bin
#   boot_app0.bin   @ 0xe000   <- Arduino-ESP32 package
#   firmware.bin    @ 0x10000  <- .pio/build/<env>/firmware.bin (also the OTA image)
#
# Then: bump "build"/"fw_version" in the server config, commit, push,
# redeploy via Portainer (without image repull).
set -e
cd "$(dirname "$0")/.."

ENV="${1:-ee02}"
BUILD_DIR=".pio/build/$ENV"
OUT_DIR="server/firmware"
PIO_PKG="$HOME/.platformio/packages/framework-arduinoespressif32"

for f in bootloader.bin partitions.bin firmware.bin; do
  if [ ! -f "$BUILD_DIR/$f" ]; then
    echo "error: $BUILD_DIR/$f missing -- run 'pio run -e $ENV' first" >&2
    exit 1
  fi
done
if [ ! -f "$PIO_PKG/tools/partitions/boot_app0.bin" ]; then
  echo "error: boot_app0.bin not found in $PIO_PKG" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
cp "$BUILD_DIR/bootloader.bin" "$BUILD_DIR/partitions.bin" "$BUILD_DIR/firmware.bin" "$OUT_DIR/"
cp "$PIO_PKG/tools/partitions/boot_app0.bin" "$OUT_DIR/"

echo "packaged into $OUT_DIR/:"
ls -la "$OUT_DIR"/*.bin
md5sum "$OUT_DIR"/*.bin 2>/dev/null || md5 "$OUT_DIR"/*.bin

# Sanity: firmware.bin must look like an ESP32 app image (magic 0xE9).
magic=$(od -A n -t x1 -N 1 "$OUT_DIR/firmware.bin" | tr -d ' \n')
if [ "$magic" != "e9" ]; then
  echo "warning: firmware.bin magic is 0x$magic, expected 0xe9" >&2
fi
echo "done -- bump build/fw_version in server config, commit, push, redeploy."
