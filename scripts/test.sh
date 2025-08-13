#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

echo "[test] Running pytest..."
pytest -q || { echo "[test] Tests failed" >&2; exit 1; }
echo "[test] OK"

