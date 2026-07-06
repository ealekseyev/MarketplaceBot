#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi

.venv/bin/pip install \
  -e ./src/fb_marketplace \
  -e ./src/fb_store \
  -e ./src/fb_agent \
  -e ./src/fb_telegram \
  -e ./src/fb_marketplace_mock \
  -e .
