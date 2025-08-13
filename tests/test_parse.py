import json
from pathlib import Path

from factbase.parser import extract_transcript


def test_parse_fixture():
    html = Path("tests/fixtures/rollcall_sample.html").read_text(encoding="utf-8")
    data = extract_transcript(html, "https://rollcall.com/factbase/trump/transcript/sample")
    assert data["title"]
    assert data["date"] == "2023-05-01"
    segs = data["segments"]
    assert len(segs) >= 3
    assert segs[0]["segment_order"] == 1
    assert segs[0]["start_time"] == 0
    assert segs[1]["start_time"] == 5
    assert segs[2]["end_time"] == 20
    assert all(isinstance(s.get("start_time"), int) for s in segs)
    assert data["speakers"][0]["name"] in ("Donald Trump", "Reporter")

