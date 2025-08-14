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

    client_headers = {"User-Agent": config.user_agent, "Accept": "text/html,*/*"}
    limiter = RateLimiter(config.rps)
    sem = asyncio.Semaphore(config.concurrency)
    stats = {"found": len(urls), "fetched": 0, "updated": 0, "skipped": 0, "failed": 0}

    import sqlite3
    from .db import connect

    # Connection pool for better database performance
    connections = []
    for _ in range(min(8, config.concurrency // 8)):  # Create connection pool
        conn = connect(db_path)
        init_db(conn)
        conn.execute("PRAGMA journal_mode=WAL")  # WAL mode for better concurrency
        conn.execute("PRAGMA synchronous=NORMAL")  # Faster writes
        conn.execute("PRAGMA cache_size=10000")  # Larger cache
        conn.execute("PRAGMA temp_store=memory")  # Use memory for temp storage
        connections.append(conn)
    
    conn_idx = 0
    lock = asyncio.Lock()

    # Batch processing for database operations
    db_batch = []
    batch_size = 50
    
    async def flush_batch():
        if not db_batch:
            return
        async with lock:
            nonlocal conn_idx
            conn = connections[conn_idx % len(connections)]
            conn_idx += 1
            
            try:
                conn.execute("BEGIN TRANSACTION")
                for batch_item in db_batch:
                    t, data = batch_item
                    upsert_transcript(conn, t)
                    conn.execute("DELETE FROM segments WHERE transcript_id=?", (t["id"],))
                    bulk_insert_segments(conn, t["id"], data.get("segments", []))
                    replace_speakers(conn, t["id"], data.get("speakers", []))
                    replace_topics(conn, t["id"], [{"topic": x, "score": None} for x in data.get("topics", [])])
                    replace_entities(conn, t["id"], data.get("entities", []))
                conn.execute("COMMIT")
                stats["updated"] += len(db_batch)
            except Exception as e:
                conn.execute("ROLLBACK")
                LOGGER.error("Batch DB operation failed: %s", e)
                stats["failed"] += len(db_batch)
            finally:
                db_batch.clear()

    async with httpx.AsyncClient(
        follow_redirects=True, 
        headers=client_headers,
        limits=httpx.Limits(max_keepalive_connections=config.concurrency, max_connections=config.concurrency * 2),
        timeout=httpx.Timeout(60.0, connect=10.0)
    ) as client:
        async def worker(u: str):
            async with sem:
                try:
                    r = await fetch_with_retries(client, u, client_headers, limiter)
                    if r.status_code == 304:
                        stats["skipped"] += 1
                        return
                    html = r.text
                    data = extract_transcript(html, u)
                    
                    # Write raw html
                    html_dir = os.path.join(config.out_dir, "html")
                    os.makedirs(html_dir, exist_ok=True)
                    with open(os.path.join(html_dir, f"{data['id']}.html"), "w", encoding="utf-8") as f:
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
                    
                    # Add to batch instead of immediate DB write
                    async with lock:
                        db_batch.append((t, data))
                        if len(db_batch) >= batch_size:
                            await flush_batch()
                    
                    stats["fetched"] += 1
                    LOGGER.info("scraped %s: %d segments", t["id"], len(data.get("segments", [])))
                except Exception as e:  # noqa: BLE001
                    LOGGER.exception("failed %s: %s", u, e)
                    stats["failed"] += 1

        await asyncio.gather(*(worker(u) for u in urls))
        
        # Flush remaining batch
        await flush_batch()

    # Close all connections
    for conn in connections:
        conn.close()
    return stats

