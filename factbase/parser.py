from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from .utils import normalize_whitespace, parse_timestamp_range, sha1_16


LOGGER = logging.getLogger(__name__)


def extract_transcript(html: str, url: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    # Remove obvious boilerplate
    for sel in ["nav", "header", "footer", "aside", "script", "style"]:
        for el in soup.select(sel):
            el.decompose()

    title = None
    if soup.title and soup.title.string:
        title = soup.title.get_text(strip=True)
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True) or title

    # Date heuristics
    date = None
    time_el = soup.find("time")
    if time_el and (time_el.get("datetime") or time_el.get_text(strip=True)):
        cand = time_el.get("datetime") or time_el.get_text(strip=True)
        date = _normalize_date(cand)
    if not date:
        # search common patterns
        m = re.search(r"(\d{4})[-/](\d{2})[-/](\d{2})", soup.get_text(" ", strip=True))
        if m:
            date = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    # Find transcript container by timestamp pattern presence
    container = None
    for cand in soup.find_all(True):
        text = cand.get_text(" ", strip=True)[:1000]
        if re.search(r"\b\d{2}:\d{2}:\d{2}\b", text):
            container = cand
            break
    if not container:
        container = soup

    # Extract segments by scanning for timestamp prefixes
    segments: List[dict] = []
    order = 0
    prev_start = None
    for block in container.stripped_strings:
        start, end, dur = parse_timestamp_range(block)
        if start is None:
            continue
        # Extract remainder text after the timestamp
        text_after = re.sub(r"^\s*" + re.escape(block[: block.find(":") + 1]) + r".*?\)?:?\s*", "", block)
        # Speaker heuristic: look backwards in the string for a label like "Name:" before text
        speaker_name = None
        msp = re.search(r"([A-Z][A-Za-z\.\-\s']{2,40}):\s*", text_after)
        if msp:
            speaker_name = msp.group(1).strip()
            text_after = text_after[msp.end() :]
        text_after = normalize_whitespace(text_after)
        order += 1
        segments.append(
            {
                "segment_order": order,
                "speaker_name": speaker_name,
                "speaker_id": sha1_16((speaker_name or "unknown").lower()),
                "start_time": start,
                "end_time": end,
                "duration": dur if dur is not None and dur >= 0 else (end - start if end else None),
                "text": text_after,
                "sentiment_score": None,
            }
        )

    # Infer end times where missing
    for i, seg in enumerate(segments):
        if seg["end_time"] is None and i + 1 < len(segments):
            seg["end_time"] = segments[i + 1]["start_time"]
        if seg["end_time"] is not None and seg["duration"] is None:
            seg["duration"] = max(0, seg["end_time"] - seg["start_time"])

    full_text = normalize_whitespace("\n\n".join(s.get("text", "") for s in segments))
    duration_seconds = 0
    if segments:
        last = segments[-1]
        duration_seconds = (last["end_time"] or last["start_time"]) or 0

    # Stable id from slug or URL
    slug = url.rstrip("/").split("/")[-1]
    id_ = slug if slug else sha1_16(url)

    # Speaker summary
    speakers = _aggregate_speakers(segments)

    return {
        "id": id_,
        "url": url,
        "title": title,
        "date": date,
        "segments": segments,
        "full_text": full_text,
        "duration_seconds": duration_seconds,
        "speakers": speakers,
        "topics": [],
        "entities": [],
    }


def _normalize_date(s: str) -> Optional[str]:
    s = s.strip()
    # Try ISO first
    m = re.match(r"(\d{4})[-/](\d{2})[-/](\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # Try Month dd, yyyy
    try:
        from dateutil import parser as dp  # lazy

        dt = dp.parse(s, fuzzy=True)
        return dt.date().isoformat()
    except Exception:
        return None


def _aggregate_speakers(segments: List[dict]) -> List[dict]:
    stats: dict[str, dict] = {}
    total_seconds = sum((s.get("duration") or 0) for s in segments) or 1
    for s in segments:
        name = s.get("speaker_name") or "Unknown"
        sid = s.get("speaker_id") or sha1_16(name.lower())
        d = stats.setdefault(
            name,
            {"name": name, "speaker_id": sid, "sentences": 0, "words": 0, "seconds": 0},
        )
        d["sentences"] += max(1, s.get("text", "").count(".") + s.get("text", "").count("!"))
        d["words"] += len((s.get("text") or "").split())
        d["seconds"] += s.get("duration") or 0
    # percentage
    out = []
    for v in stats.values():
        v["percentage"] = round(100.0 * (v["seconds"] / total_seconds), 2)
        out.append(v)
    # sort by seconds desc
    out.sort(key=lambda x: (-x["seconds"], x["name"]))
    return out

