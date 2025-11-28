from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import List

import httpx

from .config import Config
from .db import (
    bulk_insert_segments,
    init_db,
    replace_entities,
    replace_speakers,
    replace_topics,
    upsert_transcript,
)
from .parser import extract_transcript
from .utils import RateLimiter, ensure_dirs, fetch_with_retries


LOGGER = logging.getLogger(__name__)


async def scrape_all(config: Config, db_path: str, discovered_jsonl: str) -> dict:
    ensure_dirs(config.out_dir, config.state_dir, os.path.dirname(db_path))
    # Load URLs
    urls: List[str] = []
    if os.path.exists(discovered_jsonl):
        with open(discovered_jsonl, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    urls.append(json.loads(line)["url"])
                except Exception:
                    continue
    urls = list(dict.fromkeys(urls))
    if not urls:
        LOGGER.warning("No URLs to scrape from %s", discovered_jsonl)
        return {"found": 0, "fetched": 0, "updated": 0, "skipped": 0, "failed": 0}

    client_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "DNT": "1",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Cache-Control": "max-age=0",
        "Referer": "https://rollcall.com/factbase/transcripts/",
    }
    limiter = RateLimiter(config.rps)
    stats = {"found": len(urls), "fetched": 0, "updated": 0, "skipped": 0, "failed": 0}

    # Progress tracking for long runs
    import time
    start_time = time.time()
    last_progress = 0
    failed_urls = set()  # Track URLs that repeatedly fail

    import sqlite3
    from .db import connect

    # Connection pool for better database performance
    num_db_connections = max(4, min(8, config.concurrency // 4))
    connections = []
    for _ in range(num_db_connections):
        conn = connect(db_path)
        init_db(conn)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA cache_size=10000")
        conn.execute("PRAGMA temp_store=memory")
        connections.append(conn)

    conn_idx = 0

    # Separate locks for better concurrency
    append_lock = asyncio.Lock()  # Fast lock for batch append
    flush_lock = asyncio.Lock()   # Separate lock for DB flush

    # Batch processing for database operations
    db_batch = []
    batch_size = 25

    # Client recycling to prevent stale connections
    REQUEST_RECYCLE_THRESHOLD = 500
    request_count = [0]  # Use list for nonlocal mutation
    client_holder = [None]  # Holder for client reference

    def create_client():
        return httpx.AsyncClient(
            follow_redirects=True,
            headers=client_headers,
            limits=httpx.Limits(
                max_keepalive_connections=config.concurrency,
                max_connections=config.concurrency * 2,
                keepalive_expiry=15.0
            ),
            timeout=httpx.Timeout(30.0, connect=5.0)
        )

    # Progress logging function
    def log_progress():
        nonlocal last_progress
        total_processed = stats["fetched"] + stats["skipped"] + stats["failed"]
        if total_processed > 0 and total_processed - last_progress >= 100:
            elapsed = time.time() - start_time
            rate = total_processed / elapsed if elapsed > 0 else 0
            remaining = len(urls) - total_processed
            eta = remaining / rate if rate > 0 else 0
            LOGGER.info(f"Progress: {total_processed}/{len(urls)} ({total_processed/len(urls)*100:.1f}%) - "
                       f"Rate: {rate:.1f}/s - ETA: {eta/60:.1f}min - "
                       f"Fetched: {stats['fetched']}, Skipped: {stats['skipped']}, Failed: {stats['failed']}")
            last_progress = total_processed

    async def flush_batch():
        if not db_batch:
            return
        async with flush_lock:
            nonlocal conn_idx
            conn = connections[conn_idx % len(connections)]
            conn_idx += 1

            batch_copy = db_batch.copy()
            db_batch.clear()

            try:
                conn.execute("BEGIN TRANSACTION")
                for batch_item in batch_copy:
                    t, data = batch_item
                    upsert_transcript(conn, t)
                    conn.execute("DELETE FROM segments WHERE transcript_id=?", (t["id"],))
                    bulk_insert_segments(conn, t["id"], data.get("segments", []))
                    replace_speakers(conn, t["id"], data.get("speakers", []))
                    replace_topics(conn, t["id"], [{"topic": x, "score": None} for x in data.get("topics", [])])
                    replace_entities(conn, t["id"], data.get("entities", []))
                conn.execute("COMMIT")
                stats["updated"] += len(batch_copy)
            except Exception as e:
                conn.execute("ROLLBACK")
                LOGGER.error("Batch DB operation failed: %s", e)
                stats["failed"] += len(batch_copy)

    # Worker pool pattern using asyncio.Queue
    url_queue = asyncio.Queue()
    for url in urls:
        await url_queue.put(url)

    client_holder[0] = create_client()

    async def worker():
        while True:
            try:
                u = url_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            try:
                # Skip URLs that have failed multiple times
                if u in failed_urls:
                    stats["skipped"] += 1
                    log_progress()
                    continue

                # First, try to extract ID from URL to check if HTML already exists
                temp_data = extract_transcript("", u)
                html_dir = os.path.join(config.out_dir, "html")
                html_file = os.path.join(html_dir, f"{temp_data['id']}.html")

                # Skip if HTML file already exists
                if os.path.exists(html_file):
                    stats["skipped"] += 1
                    log_progress()
                    continue

                # Client recycling check
                request_count[0] += 1
                if request_count[0] >= REQUEST_RECYCLE_THRESHOLD:
                    async with append_lock:
                        if request_count[0] >= REQUEST_RECYCLE_THRESHOLD:
                            old_client = client_holder[0]
                            client_holder[0] = create_client()
                            request_count[0] = 0
                            try:
                                await old_client.aclose()
                            except Exception:
                                pass

                r = await fetch_with_retries(client_holder[0], u, client_headers, limiter)
                if r.status_code == 304:
                    stats["skipped"] += 1
                    log_progress()
                    continue
                html = r.text
                data = extract_transcript(html, u)

                # Write raw html
                os.makedirs(html_dir, exist_ok=True)
                with open(html_file, "w", encoding="utf-8") as f:
                    f.write(html)

                t = {
                    "id": data["id"],
                    "url": data["url"],
                    "title": data.get("title"),
                    "date": data.get("date"),
                    "duration_seconds": data.get("duration_seconds"),
                    "full_text": data.get("full_text"),
                    "raw_html": html,
                    "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                }

                # Add to batch with separate lock
                should_flush = False
                async with append_lock:
                    db_batch.append((t, data))
                    if len(db_batch) >= batch_size:
                        should_flush = True

                if should_flush:
                    await flush_batch()

                stats["fetched"] += 1
                log_progress()

                # Memory cleanup for large responses
                if len(html) > 500000:
                    del html
                    import gc
                    gc.collect()

            except Exception as e:
                LOGGER.exception("failed %s: %s", u, e)
                failed_urls.add(u)
                stats["failed"] += 1
                log_progress()

    # Create worker tasks (only concurrency number of workers)
    workers = [asyncio.create_task(worker()) for _ in range(config.concurrency)]
    await asyncio.gather(*workers)

    # Flush remaining batch
    await flush_batch()

    # Cleanup
    if client_holder[0]:
        await client_holder[0].aclose()
    for conn in connections:
        conn.close()
    return stats

