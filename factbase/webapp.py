from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List
import os

from flask import Flask, jsonify, request, send_from_directory


def create_app(conn: sqlite3.Connection) -> Flask:
    app = Flask(__name__, static_folder=None)

    # Resolve absolute path to bundled static assets regardless of CWD
    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "static"))

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.get("/static/<path:path>")
    def static_files(path):
        return send_from_directory(static_dir, path)

    @app.get("/api/speakers")
    def api_speakers():
        cur = conn.execute(
            "SELECT name, COUNT(*) as segments, SUM(seconds) as seconds FROM speakers GROUP BY name ORDER BY seconds DESC NULLS LAST"
        )
        items = [{"name": r["name"], "segments": r["segments"], "seconds": r["seconds"]} for r in cur]
        return jsonify(items)

    @app.get("/api/transcript/<tid>")
    def api_transcript(tid: str):
        t = conn.execute("SELECT * FROM transcripts WHERE id=?", (tid,)).fetchone()
        if not t:
            return jsonify({"error": "not found"}), 404
        segs = [dict(r) for r in conn.execute(
            "SELECT segment_order, speaker_name, speaker_id, start_time, end_time, duration, text FROM segments WHERE transcript_id=? ORDER BY segment_order",
            (tid,),
        )]
        speakers = [dict(r) for r in conn.execute(
            "SELECT name, speaker_id, sentences, words, seconds, percentage FROM speakers WHERE transcript_id=? ORDER BY seconds DESC",
            (tid,),
        )]
        topics = [r["topic"] for r in conn.execute("SELECT topic FROM topics WHERE transcript_id=?", (tid,))]
        entities = [r["entity"] for r in conn.execute("SELECT entity FROM entities WHERE transcript_id=?", (tid,))]
        data = {
            "id": t["id"],
            "url": t["url"],
            "title": t["title"],
            "date": t["date"],
            "speakers": speakers,
            "segments": segs,
            "full_text": t["full_text"],
            "topics": topics,
            "entities": entities,
        }
        return jsonify(data)

    @app.get("/api/transcript/<tid>.txt")
    def api_transcript_txt(tid: str):
        t = conn.execute("SELECT title FROM transcripts WHERE id=?", (tid,)).fetchone()
        if not t:
            return ("not found", 404, {"Content-Type": "text/plain; charset=utf-8"})
        lines = []
        for r in conn.execute(
            "SELECT start_time, end_time, speaker_name, text FROM segments WHERE transcript_id=? ORDER BY segment_order",
            (tid,),
        ):
            st = r["start_time"] or 0
            et = r["end_time"] or st
            lines.append(f"{_fmt(st)}-{_fmt(et)} {r['speaker_name'] or ''}: {r['text']}")
        body = (t["title"] or tid) + "\n\n" + "\n".join(lines)
        return (body, 200, {"Content-Type": "text/plain; charset=utf-8"})

    @app.get("/api/search")
    def api_search():
        q = request.args.get("q", "").strip()
        speaker_filter = request.args.get("speaker")
        start = request.args.get("start")
        end = request.args.get("end")
        topic = request.args.get("topic")
        entity = request.args.get("entity")
        min_duration = request.args.get("min_duration", type=int)
        page = max(1, request.args.get("page", default=1, type=int))
        page_size = max(1, min(100, request.args.get("page_size", default=20, type=int)))
        sort = request.args.get("sort", default="relevance")

        fts_query, params = _build_fts_query(q)

        where = ["1=1"]
        if speaker_filter:
            names = [x.strip() for x in speaker_filter.split(",") if x.strip()]
            where.append(
                "(" + " OR ".join(["segments.speaker_name LIKE ?" for _ in names]) + ")"
            )
            params.extend([f"%{n}%" for n in names])
        if start:
            where.append("transcripts.date >= ?")
            params.append(start)
        if end:
            where.append("transcripts.date <= ?")
            params.append(end)
        if min_duration is not None:
            where.append("segments.duration >= ?")
            params.append(min_duration)
        if topic:
            where.append("EXISTS (SELECT 1 FROM topics tp WHERE tp.transcript_id=transcripts.id AND tp.topic LIKE ?)")
            params.append(f"%{topic}%")
        if entity:
            where.append("EXISTS (SELECT 1 FROM entities en WHERE en.transcript_id=transcripts.id AND en.entity LIKE ?)")
            params.append(f"%{entity}%")

        order_by = ""
        if sort == "newest":
            order_by = "ORDER BY transcripts.date DESC"
        elif sort == "oldest":
            order_by = "ORDER BY transcripts.date ASC"
        else:
            order_by = "ORDER BY bm25(segments_fts)"

        sql = f"""
            WITH ranked AS (
                SELECT segments.rowid as rowid, segments.transcript_id as tid
                FROM segments_fts
                JOIN segments ON segments.id = segments_fts.rowid
                JOIN transcripts ON transcripts.id = segments.transcript_id
                WHERE segments_fts MATCH ? AND {' AND '.join(where)}
            )
            SELECT DISTINCT transcripts.id, transcripts.title, transcripts.date,
                (SELECT json_group_array(name) FROM (
                    SELECT name FROM speakers sp WHERE sp.transcript_id=transcripts.id ORDER BY seconds DESC LIMIT 3
                )) as top_speakers,
                snippet(segments_fts, 0, '<mark>', '</mark>', ' … ', 12) as snippet
            FROM ranked
            JOIN segments_fts ON segments_fts.rowid = ranked.rowid
            JOIN transcripts ON transcripts.id = ranked.tid
            JOIN segments ON segments.id = ranked.rowid
            {order_by}
            LIMIT ? OFFSET ?
        """

        count_sql = f"""
            SELECT COUNT(DISTINCT transcripts.id) as cnt
            FROM segments_fts
            JOIN segments ON segments.id = segments_fts.rowid
            JOIN transcripts ON transcripts.id = segments.transcript_id
            WHERE segments_fts MATCH ? AND {' AND '.join(where)}
        """

        all_params = [fts_query] + params
        total = conn.execute(count_sql, all_params).fetchone()[0]
        items = []
        for r in conn.execute(sql, all_params + [page_size, (page - 1) * page_size]):
            items.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "date": r["date"],
                    "top_speakers": json.loads(r["top_speakers"]) if r["top_speakers"] else [],
                    "snippet": r["snippet"],
                }
            )

        return jsonify({"total": total, "page": page, "page_size": page_size, "items": items})

    return app


def _build_fts_query(q: str) -> tuple[str, list]:
    # Field scoping: title:, speaker:, text:
    # Map to columns: title, speaker_name, text
    # Keep boolean ops and quotes as-is for FTS5
    tokens = q
    tokens = tokens.replace("title:", "title:")
    tokens = tokens.replace("speaker:", "speaker_name:")
    tokens = tokens.replace("text:", "text:")
    if not tokens:
        # Empty query -> match nothing (safe default)
        tokens = '""'
    # FTS5 uses prefix with *; pass through
    return tokens, []


def _fmt(s: int) -> str:
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d}"
