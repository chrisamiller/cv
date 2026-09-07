#!/usr/bin/env bash
# Build the static site and serve it locally for preview.
set -euo pipefail
cd "$(dirname "$0")"
python3 build.py --serve
