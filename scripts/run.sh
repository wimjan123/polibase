#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

START_URL=${1:-https://rollcall.com/factbase/transcripts/}
OUT_DIR=${2:-out}
DB_PATH=${3:-out/transcripts.db}
HOST=${4:-0.0.0.0}
PORT=${5:-5000}

echo "[run] Discovering..."
factbase discover --start "$START_URL" --max-items 400 --out "$OUT_DIR" --state state || { echo "[run] discover failed" >&2; exit 1; }

echo "[run] Scraping..."
factbase scrape --out "$OUT_DIR" --db "$DB_PATH" || { echo "[run] scrape failed" >&2; exit 1; }

echo "[run] Exporting..."
factbase export --db "$DB_PATH" --out "$OUT_DIR" || { echo "[run] export failed" >&2; exit 1; }

echo "[run] Starting web UI at http://$HOST:$PORT ..."
factbase web --db "$DB_PATH" --host "$HOST" --port "$PORT" || { echo "[run] web failed" >&2; exit 1; }
