#!/usr/bin/env sh
set -eu

. .venv/bin/activate || { echo "Activate venv first: . .venv/bin/activate"; exit 1; }

OUT_DIR=${1:-out}
SPEAKERS=${2:-trump,biden,harris}

echo "[discover] Discovering URLs for speakers: $SPEAKERS into $OUT_DIR ..."
factbase discover --speakers "$SPEAKERS" --max-items 10000 --out "$OUT_DIR" --state state || {
  echo "[discover] Failed" >&2; exit 1;
}

COUNT=$(wc -l < "$OUT_DIR/discovered_urls.jsonl" || echo 0)
if [ "${COUNT:-0}" -eq 0 ]; then
  echo "[discover] Zero results. See $OUT_DIR/listing_dump.html for debugging." >&2
  exit 2
fi
echo "[discover] Found $COUNT URLs"
