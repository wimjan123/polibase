#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

OUT_DIR=${1:-out}
DB_PATH=${2:-out/transcripts.db}

echo "[export] Exporting JSONL and CSV to $OUT_DIR ..."
factbase export --db "$DB_PATH" --out "$OUT_DIR" || { echo "[export] Failed" >&2; exit 1; }
echo "[export] Done"

