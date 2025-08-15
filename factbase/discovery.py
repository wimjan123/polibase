from __future__ import annotations

import json
import logging
import os
import re
import signal
import time
from typing import List, Set, Optional, Tuple

from playwright.sync_api import sync_playwright


LOGGER = logging.getLogger(__name__)

DETAIL_RE = re.compile(r"^https?://rollcall\.com/factbase/.+/transcript/[a-z0-9\-]+/?$")


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
    existing_index = {u: i for i, u in enumerate(existing)}

    merged = set(existing)
    merged.update(discovered)

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


def discover_urls(
    start_url: str,
    out_dir: str,
    state_dir: str,
    max_items: int = 1000,
    idle_cycles: int = 10,
    headless: bool = True,
) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)

    discovered: Set[str] = set()
    endpoints: dict = {"start_url": start_url, "observed_endpoints": []}
    
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
        # Block only images for faster loading (keep CSS/JS for functionality)
        context.route("**/*.{png,jpg,jpeg,gif,svg,woff,woff2,ttf,eot}", lambda route: route.abort())
        # Monitor network requests to debug infinite scroll
        network_requests = []
        def on_response(response):
            if 'json' in response.headers.get('content-type', ''):
                network_requests.append({
                    'url': response.url,
                    'status': response.status,
                    'headers': dict(response.headers)
                })
        context.on("response", on_response)
        page = context.new_page()
        page.set_default_navigation_timeout(30000)
        page.set_default_timeout(15000)

        LOGGER.info("Loading %s...", start_url)
        page.goto(start_url)
        LOGGER.info("Page loaded, accepting consent...")
        _accept_consent(page)

        new_in_cycle = 0
        idle = 0
        last_count = 0

        while True:
            # Store current scroll position
            prev_height = page.evaluate("document.body.scrollHeight")
            
            # Handle load more if present
            clicked = _click_load_more(page)
            
            # Try different scrolling approaches for infinite scroll
            # Method 1: Multiple scroll attempts
            for i in range(5):
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.1)
                page.evaluate("window.scrollBy(0, -100)")
                time.sleep(0.1)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                time.sleep(0.1)
                
            # Method 2: Try dispatching scroll events manually
            page.evaluate("""
                window.dispatchEvent(new Event('scroll'));
                window.dispatchEvent(new Event('scrollend'));
            """)
            
            # Method 3: Trigger intersection observers manually if they exist
            page.evaluate("""
                const sentinels = document.querySelectorAll('[class*="sentinel"], [class*="load"], [id*="load"], [data-*="load"]');
                sentinels.forEach(el => {
                    const rect = el.getBoundingClientRect();
                    if (rect.top < window.innerHeight) {
                        el.click();
                        el.dispatchEvent(new Event('intersect'));
                    }
                });
            """)
            
            # Wait longer for network requests and content loading (reduced to prevent hanging)
            time.sleep(0.8)
            
            # Check if page height increased (new content loaded)
            new_height = page.evaluate("document.body.scrollHeight")
            height_increased = new_height > prev_height
            
            _collect_links(page, discovered)

            new_in_cycle = len(discovered) - last_count
            last_count = len(discovered)
            LOGGER.info("discover: total=%d new=%d height_grew=%s idle=%d", last_count, new_in_cycle, height_increased, idle)
            
            # Save periodically every 500 links
            if len(discovered) % 500 == 0 and len(discovered) > 0:
                _save_urls(discovered, out_dir)
                LOGGER.info("Saved %d URLs to file", len(discovered))
            
            # Log network requests if any
            if network_requests:
                LOGGER.info("Network requests this cycle: %d", len(network_requests))
                for req in network_requests[-3:]:  # Show last 3
                    LOGGER.info("  -> %s [%d]", req['url'], req['status'])
                network_requests.clear()

            if len(discovered) >= max_items:
                break
                
            # Reset idle counter if we got new links OR page height increased
            if clicked or new_in_cycle > 0 or height_increased:
                idle = 0
            else:
                idle += 1
                
            if idle >= idle_cycles:
                break

        if len(discovered) == 0:
            html_dump = os.path.join(out_dir, "listing_dump.html")
            with open(html_dump, "w", encoding="utf-8") as f:
                f.write(page.content())
            LOGGER.warning("Zero results discovered. Saved DOM to %s", html_dump)

        # Persist endpoints (simplified)
        with open(os.path.join(state_dir, "endpoints.json"), "w", encoding="utf-8") as f:
            json.dump({"start_url": start_url}, f)

        browser.close()

    # Final save
    _save_urls(discovered, out_dir)
    LOGGER.info("Final save: %d URLs to discovered_urls.jsonl", len(discovered))

    return sorted(discovered)


def _click_load_more(page) -> bool:
    try:
        # Attempt to click any load-more like button
        buttons = page.locator("button, a").all()
        for b in buttons:
            try:
                txt = (b.inner_text() or "").strip().lower()
            except Exception:
                continue
            if txt in ("load more", "show more", "more", "loadmore", "next", "see more", "view more", "continue"):
                b.click(timeout=1000)
                time.sleep(0.1)
                return True
        return False
    except Exception:
        return False


def _accept_consent(page) -> None:
    try:
        for label in ["Accept", "I agree", "Agree", "Consent", "Continue"]:
            locator = page.get_by_text(label, exact=False)
            if locator.count() > 0:
                locator.first.click(timeout=1000)
                time.sleep(0.1)
                break
    except Exception:
        pass


def _collect_links(page, discovered: Set[str]) -> None:
    # Get all hrefs at once with evaluate
    hrefs = page.evaluate("""
        Array.from(document.querySelectorAll('a[href]')).map(a => a.href)
    """)
    
    for href in hrefs:
        if href and DETAIL_RE.match(href):
            discovered.add(href)
