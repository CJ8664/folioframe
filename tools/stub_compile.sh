#!/bin/bash
# Level 2 verification: syntax-check ALL of src/ against Arduino API stubs.
# Catches type/signature mismatches without the ESP32 toolchain.
set -e
cd "$(dirname "$0")/.."
echo "--- stub compile (src/) ---"
g++ -std=c++17 -fsyntax-only -Wall -Wextra \
  -Itest/stubs -Iinclude -Isrc \
  $(find src -name '*.cpp') \
  && echo "STUB COMPILE OK"
