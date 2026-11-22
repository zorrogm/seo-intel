#!/usr/bin/env bash
# One command setup: bash install.sh
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${PYTHON:-python3}"
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)' || {
  echo "Python 3.9 or newer is needed."; exit 1; }

"$PYTHON" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet .
# Browser used for pages built by JavaScript
.venv/bin/python -m playwright install chromium || echo "Browser download failed, rendering will be skipped."

[ -f .env ] || cp .env.example .env
echo "Installed. Try: ./seo-intel example.com --competitor example.org"
