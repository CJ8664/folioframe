#!/bin/bash
# Build & run all native unit tests (Level 1). Zero dependencies beyond g++.
set -e
cd "$(dirname "$0")/.."

CORE="src/core/QuietHours.cpp src/core/Scheduler.cpp src/core/BatteryCurve.cpp \
      src/core/UrlTemplate.cpp src/core/OtaManifest.cpp src/core/Validate.cpp"
mkdir -p build/tests
pass=0
fail=0
for t in test/test_*.cpp; do
  name=$(basename "$t" .cpp)
  if g++ -std=c++17 -Wall -Wextra -Itest -Isrc "$t" $CORE \
      -o "build/tests/$name" 2> "build/tests/$name.err"; then
    if "build/tests/$name" > "build/tests/$name.log" 2>&1; then
      echo "PASS $name"
      pass=$((pass + 1))
    else
      echo "FAIL $name (test failures)"
      cat "build/tests/$name.log"
      fail=$((fail + 1))
    fi
  else
    echo "FAIL $name (compile)"
    cat "build/tests/$name.err"
    fail=$((fail + 1))
  fi
done
echo "---"
echo "$pass passed, $fail failed"
[ "$fail" -eq 0 ]
