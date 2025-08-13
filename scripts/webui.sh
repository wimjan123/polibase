#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

DB_PATH=${1:-out/transcripts.db}
HOST=${2:-0.0.0.0}
PORT=${3:-5173}

echo "[webui] Serving separate Web UI on http://$HOST:$PORT ..."
python -m webui.server --db "$DB_PATH" --host "$HOST" --port "$PORT" || { echo "[webui] Failed" >&2; exit 1; }

