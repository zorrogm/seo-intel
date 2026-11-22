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
# The browser driver needs this library on bare Linux
if command -v apt-get >/dev/null 2>&1 && [ "$(id -u)" = "0" ]; then
  apt-get install -y -qq libatomic1 >/dev/null 2>&1 || true
fi
# On Linux, system libraries come along when allowed
.venv/bin/python -m playwright install --with-deps chromium 2>/dev/null \
  || .venv/bin/python -m playwright install chromium \
  || echo "Browser setup failed, rendering will be skipped."

[ -f .env ] || cp .env.example .env
echo "Installed. Try: ./seo-intel example.com --competitor example.org"
