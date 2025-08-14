from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import List, Set

from playwright.sync_api import sync_playwright


LOGGER = logging.getLogger(__name__)

DETAIL_RE = re.compile(r"^https?://rollcall\.com/factbase/.+/transcript/[a-z0-9\-]+/?$")


def discover_urls(
    start_url: str,
    out_dir: str,
    state_dir: str,
    max_items: int = 1000,
    idle_cycles: int = 20,
    headless: bool = True,
) -> List[str]:
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(state_dir, exist_ok=True)

    discovered: Set[str] = set()
    endpoints: dict = {"start_url": start_url, "observed_endpoints": []}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled', '--disable-dev-shm-usage', '--no-sandbox']
        )
        context = browser.new_context(
            user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        # Block images, CSS, fonts for faster loading
        context.route("**/*.{png,jpg,jpeg,gif,svg,css,woff,woff2,ttf,eot}", lambda route: route.abort())
        # Removed network logging for speed
        page = context.new_page()
        page.set_default_navigation_timeout(10000)
        page.set_default_timeout(5000)

        page.goto(start_url)
        _accept_consent(page)

        new_in_cycle = 0
        idle = 0
        last_count = 0

        while True:
            # Handle load more if present
            clicked = _click_load_more(page)
            # Scroll down and collect in one pass
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(0.1)
            _collect_links(page, discovered)

            new_in_cycle = len(discovered) - last_count
            last_count = len(discovered)
            LOGGER.info("discover: total=%d new=%d", last_count, new_in_cycle)

            if len(discovered) >= max_items:
                break
            if not clicked and new_in_cycle == 0:
                idle += 1
            else:
                idle = 0
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

    # Write JSONL
    out_path = os.path.join(out_dir, "discovered_urls.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for u in sorted(discovered):
            f.write(json.dumps({"url": u}) + "\n")

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

