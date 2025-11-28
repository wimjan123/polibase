from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import re
import time
from datetime import datetime
from typing import Optional, Tuple

import httpx


logger = logging.getLogger(__name__)

TIMESTAMP_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2})(?:-(\d{2}):(\d{2}):(\d{2}))?\s*(?:\((\d+)\s*sec\))?"
)


def sha1_16(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


def normalize_whitespace(text: str) -> str:
    if text is None:
        return ""
    # Remove zero-width & soft hyphens
    text = (
        text.replace("\ufeff", "")
        .replace("\u200b", "")
        .replace("\u00ad", "")
        .replace("\u2060", "")
    )
    # Collapse spaces but keep newlines
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n\s+\n", "\n\n", text)
    return text.strip()


def parse_timestamp_range(s: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    m = TIMESTAMP_RE.search(s)
    if not m:
        return None, None, None
    h1, m1, s1, h2, m2, s2, sec = m.groups()
    start = int(h1) * 3600 + int(m1) * 60 + int(s1)
    end = None
    if h2 is not None:
        end = int(h2) * 3600 + int(m2) * 60 + int(s2)
    dur = int(sec) if sec else None
    return start, end, dur


class RateLimiter:
    """Token bucket rate limiter for concurrent access."""

    def __init__(self, rps: float):
        self.rps = max(rps, 0.001)
        self.tokens = rps  # Start with full bucket
        self.max_tokens = rps * 2  # Allow small burst
        self.last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def wait(self):
        async with self._lock:
            now = time.monotonic()
            # Refill tokens based on elapsed time
            elapsed = now - self.last_refill
            self.tokens = min(self.max_tokens, self.tokens + elapsed * self.rps)
            self.last_refill = now

            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return

            # Calculate wait time for next token
            wait_time = (1.0 - self.tokens) / self.rps
            self.tokens = 0

        await asyncio.sleep(wait_time)


async def fetch_with_retries(
    client: httpx.AsyncClient,
    url: str,
    headers: dict,
    limiter: RateLimiter,
    max_retries: int = 5,  # More retries for server errors
) -> httpx.Response:
    backoff = 2.0  # Longer initial backoff for server recovery
    for attempt in range(max_retries + 1):
        await limiter.wait()
        try:
            r = await client.get(url, headers=headers, timeout=30)
            if r.status_code in (429, 500, 502, 503, 504):
                if attempt >= max_retries:
                    logger.warning("server busy after %d attempts: %s", attempt + 1, url)
                    raise httpx.HTTPStatusError("server busy", request=r.request, response=r)
                # Exponential backoff for server errors - give server time to recover
                wait_time = backoff * (2 ** attempt)  # 2s, 4s, 8s, 16s, 32s
                logger.info("Server busy (attempt %d/%d), waiting %.1fs before retry: %s",
                           attempt + 1, max_retries + 1, wait_time, url)
                await asyncio.sleep(wait_time)
                continue
            return r
        except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as e:
            if attempt >= max_retries:
                logger.warning("fetch failed %s after %d attempts: %s", url, attempt + 1, e)
                raise
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 10.0)  # Cap at 10 seconds
        except Exception as e:  # noqa: BLE001
            logger.warning("fetch failed %s: %s", url, e)
            raise


def ensure_dirs(*paths: str) -> None:
    for p in paths:
        os.makedirs(p, exist_ok=True)


def iso_date(dt: datetime | None) -> Optional[str]:
    return dt.date().isoformat() if dt else None


