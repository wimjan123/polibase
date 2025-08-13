#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

DB_PATH=${1:-out/transcripts.db}
HOST=${2:-0.0.0.0}
PORT=${3:-5000}

echo "[web] Serving on http://$HOST:$PORT ..."
factbase web --db "$DB_PATH" --host "$HOST" --port "$PORT" || { echo "[web] Failed" >&2; exit 1; }
