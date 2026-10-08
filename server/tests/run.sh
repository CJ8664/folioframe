#!/bin/bash
# Server unit tests (stdlib unittest, needs Pillow).
set -euo pipefail
cd "$(dirname "$0")/.."   # server/
python3 -m unittest discover -s tests -t . 2>&1 | tail -5
