#!/usr/bin/env sh
set -eu

echo "[install] Creating venv and installing dependencies..."
python3 -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
if [ -f requirements.txt ]; then
  pip install -r requirements.txt
fi

echo "[install] Installing package (editable) and Playwright browsers..."
pip install -e .

# Install Chromium for headless discovery
python - <<'PY'
import sys
try:
    from playwright.__main__ import main as pw
except Exception as e:
    print('[install] Playwright not available:', e)
    sys.exit(0)
import subprocess
subprocess.call([sys.executable, '-m', 'playwright', 'install', 'chromium'])
PY

echo "[install] Done. Activate venv with: . .venv/bin/activate"

