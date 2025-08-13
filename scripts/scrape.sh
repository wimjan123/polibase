#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

OUT_DIR=${1:-out}
DB_PATH=${2:-out/transcripts.db}

echo "[scrape] Scraping into $DB_PATH from $OUT_DIR/discovered_urls.jsonl ..."
factbase scrape --out "$OUT_DIR" --db "$DB_PATH" || { echo "[scrape] Failed" >&2; exit 1; }
echo "[scrape] Done"

