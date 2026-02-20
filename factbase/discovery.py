from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from typing import Dict, List, Optional, Set, Tuple

from playwright.sync_api import Page, sync_playwright


LOGGER = logging.getLogger(__name__)

DETAIL_RE = re.compile(r"^https?://rollcall\.com/factbase/.+/transcript/[a-z0-9\-=_]+/?$")

DEFAULT_SPEAKERS = ["trump", "biden", "harris"]
SEARCH_PAGE_TEMPLATE = "https://rollcall.com/factbase/{speaker}/search/"
API_ENDPOINT = "/wp-json/factbase/v1/search"


def _load_existing_urls(out_dir: str) -> List[str]:
    out_path = os.path.join(out_dir, "discovered_urls.jsonl")
    if not os.path.exists(out_path):
        return []
    urls: List[str] = []
    try:
        with open(out_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    urls.append(json.loads(line).get("url", ""))
                except Exception:
                    continue
    except Exception:
        return []
    return [u for u in urls if u]


_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}


def _date_from_url(u: str) -> Optional[Tuple[int, int, int]]:
    """Best-effort date extraction from slug for ordering.

    Returns (YYYY, MM, DD) if found, else None.
    """
    slug = u.rstrip("/").split("/")[-1].lower()
    # Try ISO-like in slug
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", slug)
    if m:
        try:
            return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass
    # Try month-name-dd-yyyy
    m2 = re.search(r"(january|february|march|april|may|june|july|august|september|october|november|december)-(\d{1,2})-(\d{4})",
                   slug)
    if m2:
        try:
            return (int(m2.group(3)), _MONTHS[m2.group(1)], int(m2.group(2)))
        except Exception:
            pass
    return None

def _save_urls(discovered: Set[str], out_dir: str) -> None:
    """Merge-save discovered URLs to JSONL without dropping existing.

    - Loads existing URLs (if any)
    - Merges with current discoveries (dedup)
    - Writes unique list ordered by parsed date desc (newest first),
      falling back to existing order for undated items.
    """
    out_path = os.path.join(out_dir, "discovered_urls.jsonl")
    existing = _load_existing_urls(out_dir)
    # Normalize trailing slashes for dedup
    def _normalize(u: str) -> str:
        return u.rstrip("/") + "/"
    existing_normalized = [_normalize(u) for u in existing]
    existing_index = {u: i for i, u in enumerate(existing_normalized)}

    merged = set(existing_normalized)
    merged.update(_normalize(u) for u in discovered)

    def sort_key(u: str):
        d = _date_from_url(u)
        # Sort by date desc first, then by original position asc (existing first),
        # finally by URL for stability.
        # Negate date for desc via tuple trick (not negating ints directly when None)
        if d is not None:
            y, m, dday = d
            date_key = (y, m, dday)
        else:
            date_key = (0, 0, 0)
        pos = existing_index.get(u, 10_000_000)
        return (-date_key[0], -date_key[1], -date_key[2], pos, u)

    ordered = sorted(merged, key=sort_key)
    with open(out_path, "w", encoding="utf-8") as f:
        for u in ordered:
            f.write(json.dumps({"url": u}) + "\n")


def _accept_consent(page: Page) -> None:
    try:
        for label in ["Accept", "I agree", "Agree", "Consent", "Continue"]:
            locator = page.get_by_text(label, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=1000)
                time.sleep(0.1)
                break
    except Exception:
        pass


def _fetch_api_page(page: Page, speaker: str, page_num: int) -> Optional[Dict]:
    """Call the Factbase search API from within the browser context."""
    url = f"{API_ENDPOINT}?media=&type=&sort=date&location=all&place=all&page={page_num}&format=json&person={speaker}"
    LOGGER.debug("Fetching API page %d for %s: %s", page_num, speaker, url)
    try:
        result = page.evaluate("""
            async (url) => {
                const resp = await fetch(url, {credentials: 'include'});
                if (!resp.ok) return {error: resp.status, statusText: resp.statusText};
                const text = await resp.text();
                try {
                    return {parsed: JSON.parse(text)};
                } catch(e) {
                    return {raw: text.substring(0, 2000)};
                }
            }
        """, url)
        if isinstance(result, dict) and "error" in result:
            LOGGER.warning("API returned status %s (%s) for %s page %d",
                          result["error"], result.get("statusText", ""), speaker, page_num)
            return None
        if isinstance(result, dict) and "raw" in result:
            LOGGER.warning("API returned non-JSON for %s page %d: %s", speaker, page_num, result["raw"][:500])
            return None
        if isinstance(result, dict) and "parsed" in result:
            parsed = result["parsed"]
            LOGGER.debug("API response for %s page %d: meta=%s, data_count=%d",
                        speaker, page_num,
                        json.dumps(parsed.get("meta", {})),
                        len(parsed.get("data", [])))
            return parsed
        LOGGER.debug("Unexpected API result type for %s page %d: %s", speaker, page_num, type(result))
        return result
    except Exception as e:
        LOGGER.error("Failed to fetch API page %d for %s: %s", page_num, speaker, e)
        return None


def _extract_urls_from_response(result: Dict, discovered: Set[str]) -> int:
    """Extract transcript URLs from an API response and add to discovered set."""
    count = 0
    data = result.get("data", [])
    for item in data:
        raw_url = item.get("factbase_url", "")
        if not raw_url:
            continue
        # Normalize: prepend https:// if missing
        if raw_url.startswith("/"):
            raw_url = "https://rollcall.com" + raw_url
        elif not raw_url.startswith("http"):
            raw_url = "https://" + raw_url
        # Normalize trailing slash
        raw_url = raw_url.rstrip("/") + "/"
        # Validate against detail pattern
        if DETAIL_RE.match(raw_url):
            if raw_url not in discovered:
                count += 1
            discovered.add(raw_url)
        else:
            LOGGER.debug("Skipped non-matching URL: %s", raw_url)
    return count


def _discover_speaker(page: Page, speaker: str, max_items: int, discovered: Set[str], out_dir: str) -> int:
    """Discover transcript URLs for a single speaker via the API."""
    search_url = SEARCH_PAGE_TEMPLATE.format(speaker=speaker)
    LOGGER.info("Navigating to search page for %s: %s", speaker, search_url)

    # Retry navigation up to 3 times (site sometimes returns ERR_NETWORK_CHANGED)
    for attempt in range(3):
        try:
            page.goto(search_url, wait_until="commit", timeout=30000)
            # Give the page time to establish session and load JS
            time.sleep(5)
            break
        except Exception as e:
            LOGGER.warning("Navigation attempt %d failed for %s: %s", attempt + 1, speaker, e)
            if attempt == 2:
                LOGGER.error("Failed to load search page for %s after 3 attempts", speaker)
                return 0
            time.sleep(2)

    _accept_consent(page)
    time.sleep(1)

    # Fetch first page to get total_pages
    result = _fetch_api_page(page, speaker, 1)
    if not result:
        LOGGER.warning("No API response for %s page 1", speaker)
        return 0

    meta = result.get("meta", {})
    total_pages = meta.get("total_pages", 0)
    records_matched = meta.get("records_matched", 0)
    LOGGER.info("Speaker %s: %d records across %d pages", speaker, records_matched, total_pages)

    total_new = _extract_urls_from_response(result, discovered)
    LOGGER.info("Speaker %s page 1: %d new URLs (total discovered: %d)", speaker, total_new, len(discovered))

    if len(discovered) >= max_items:
        return total_new

    # Paginate through remaining pages
    for page_num in range(2, total_pages + 1):
        if len(discovered) >= max_items:
            LOGGER.info("Reached max_items=%d, stopping pagination for %s", max_items, speaker)
            break

        result = _fetch_api_page(page, speaker, page_num)
        if not result:
            LOGGER.warning("No response for %s page %d, stopping pagination", speaker, page_num)
            break

        new_count = _extract_urls_from_response(result, discovered)
        total_new += new_count

        if page_num % 10 == 0:
            LOGGER.info("Speaker %s page %d/%d: %d new this page (total discovered: %d)",
                       speaker, page_num, total_pages, new_count, len(discovered))

        # Save periodically every 25 pages
        if page_num % 25 == 0:
            _save_urls(discovered, out_dir)
            LOGGER.info("Periodic save: %d URLs", len(discovered))

        # Small delay to avoid hammering the API
        time.sleep(0.1)

    LOGGER.info("Speaker %s complete: %d new URLs found", speaker, total_new)
    return total_new


def discover_urls(
    start_url: str = "",  # kept for backward compat, unused
    out_dir: str = "out",
    state_dir: str = "state",
    max_items: int = 10000,
    idle_cycles: int = 10,  # kept for backward compat, unused
    headless: bool = True,
    speakers: Optional[List[str]] = None,
) -> List[str]:
    if speakers is None:
        speakers = list(DEFAULT_SPEAKERS)

    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)

    discovered: Set[str] = set()

    # Set up signal handler for graceful shutdown
    def signal_handler(signum, frame):
        LOGGER.info("Received signal %d, saving results...", signum)
        _save_urls(discovered, out_dir)
        LOGGER.info("Saved %d URLs before exit", len(discovered))
        exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-sandbox']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        # Note: we don't block resources since route interception can interfere with fetch()
        page = context.new_page()
        page.set_default_navigation_timeout(30000)
        page.set_default_timeout(15000)

        for speaker in speakers:
            if len(discovered) >= max_items:
                LOGGER.info("Reached max_items=%d, skipping remaining speakers", max_items)
                break

            try:
                new_count = _discover_speaker(page, speaker, max_items, discovered, out_dir)
                LOGGER.info("Finished speaker %s: %d new URLs", speaker, new_count)
                # Save between speakers
                _save_urls(discovered, out_dir)
            except Exception as e:
                LOGGER.error("Error discovering speaker %s: %s", speaker, e)
                # Save what we have and continue to next speaker
                _save_urls(discovered, out_dir)
                continue

        if len(discovered) == 0:
            html_dump = os.path.join(out_dir, "listing_dump.html")
            with open(html_dump, "w", encoding="utf-8") as f:
                f.write(page.content())
            LOGGER.warning("Zero results discovered. Saved DOM to %s", html_dump)

        # Persist endpoints
        with open(os.path.join(state_dir, "endpoints.json"), "w", encoding="utf-8") as f:
            json.dump({"speakers": speakers}, f)

        browser.close()

    # Final save
    _save_urls(discovered, out_dir)
    LOGGER.info("Final save: %d URLs to discovered_urls.jsonl", len(discovered))

    return sorted(discovered)
