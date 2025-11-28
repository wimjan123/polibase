#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

OUT_DIR=${1:-out}
DB_PATH=${2:-out/transcripts.db}

# Conservative settings - rollcall.com rate-limits concurrent requests
export FACTBASE_CONCURRENCY=${FACTBASE_CONCURRENCY:-2}
export FACTBASE_RPS=${FACTBASE_RPS:-0.5}

echo "[scrape] Scraping into $DB_PATH from $OUT_DIR/discovered_urls.jsonl with ${FACTBASE_CONCURRENCY} workers at ${FACTBASE_RPS} RPS..."
factbase scrape --out "$OUT_DIR" --db "$DB_PATH" --concurrency "$FACTBASE_CONCURRENCY" --rps "$FACTBASE_RPS" || { echo "[scrape] Failed" >&2; exit 1; }
echo "[scrape] Done"

