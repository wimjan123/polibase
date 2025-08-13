from __future__ import annotations

import argparse
import os
import sqlite3
from typing import List, Dict

from flask import Flask, jsonify, request, send_from_directory

# Reuse DB connector from the main package without coupling UI routing
try:
    from factbase.db import connect, init_db
except Exception:
    # Fallback minimal connector if factbase isn't importable
    import sqlite3 as _sqlite3

    def connect(path: str) -> _sqlite3.Connection:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        conn = _sqlite3.connect(path, check_same_thread=False)
        conn.row_factory = _sqlite3.Row
        return conn

    def init_db(conn: _sqlite3.Connection) -> None:
        # no-op; assume schema exists
        pass


def create_app(conn: sqlite3.Connection) -> Flask:
    app = Flask(__name__, static_folder=None)

    static_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "static"))

    @app.get("/health")
    def health():
        return jsonify({"ok": True})

    @app.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @app.get("/assets/<path:path>")
    def static_files(path: str):
        return send_from_directory(static_dir, path)

    # --- API: Transcripts listing ---
    @app.get("/api/transcripts")
    def api_transcripts():
        q = (request.args.get("q", "") or "").strip()
        page = max(1, request.args.get("page", type=int, default=1))
        page_size = max(1, min(100, request.args.get("page_size", type=int, default=20)))

        where = []
        params: List = []
        if q:
            where.append("(title LIKE ? OR id LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])

        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        offset = (page - 1) * page_size

        count = conn.execute(f"SELECT COUNT(*) FROM transcripts {where_sql}", params).fetchone()[0]

        sql = f"""
            SELECT t.id, t.title, t.date,
                   (
                       SELECT json_group_array(name) FROM (
                           SELECT name FROM speakers s WHERE s.transcript_id = t.id
                           ORDER BY seconds DESC NULLS LAST LIMIT 3
                       )
                   ) AS top_speakers,
                   (
                       SELECT COUNT(*) FROM segments g WHERE g.transcript_id = t.id
                   ) AS segments
            FROM transcripts t
            {where_sql}
            ORDER BY COALESCE(t.date, '') DESC, t.title
            LIMIT ? OFFSET ?
        """
        items: List[Dict] = []
        for r in conn.execute(sql, params + [page_size, offset]):
            items.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "date": r["date"],
                    "top_speakers": ([] if not r["top_speakers"] else __import__("json").loads(r["top_speakers"])),
                    "segments": r["segments"],
                }
            )

        return jsonify({"total": count, "page": page, "page_size": page_size, "items": items})

    # --- API: Transcript detail with segments ---
    @app.get("/api/transcripts/<tid>")
    def api_transcript_detail(tid: str):
        t = conn.execute("SELECT * FROM transcripts WHERE id=?", (tid,)).fetchone()
        if not t:
            return jsonify({"error": "not_found"}), 404

        speakers = [dict(r) for r in conn.execute(
            """
                SELECT name, speaker_id, sentences, words, seconds, percentage
                FROM speakers WHERE transcript_id=? ORDER BY seconds DESC NULLS LAST
            """,
            (tid,),
        )]
        segs = [dict(r) for r in conn.execute(
            """
                SELECT id, segment_order, speaker_name, speaker_id, start_time, end_time, duration, text
                FROM segments WHERE transcript_id=? ORDER BY segment_order
            """,
            (tid,),
        )]

        return jsonify(
            {
                "id": t["id"],
                "title": t["title"],
                "date": t["date"],
                "url": t["url"],
                "speakers": speakers,
                "segments": segs,
            }
        )

    # Download as plain text
    @app.get("/api/transcripts/<tid>.txt")
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

    # --- API: Full-text segment search with filters ---
    @app.get("/api/search")
    def api_search():
        q = (request.args.get("q", "") or "").strip()
        speaker_filter = request.args.get("speaker")
        start = request.args.get("start")
        end = request.args.get("end")
        page = max(1, request.args.get("page", default=1, type=int))
        page_size = max(1, min(100, request.args.get("page_size", default=20, type=int)))

        fts_query, params = _build_fts_query(q)

        where = ["1=1"]
        if speaker_filter:
            names = [x.strip() for x in speaker_filter.split(",") if x.strip()]
            if names:
                where.append("(" + " OR ".join(["segments.speaker_name LIKE ?" for _ in names]) + ")")
                params.extend([f"%{n}%" for n in names])
        if start:
            where.append("transcripts.date >= ?")
            params.append(start)
        if end:
            where.append("transcripts.date <= ?")
            params.append(end)

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
            ORDER BY bm25(segments_fts)
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
        import json as _json
        for r in conn.execute(sql, all_params + [page_size, (page - 1) * page_size]):
            items.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "date": r["date"],
                    "top_speakers": _json.loads(r["top_speakers"]) if r["top_speakers"] else [],
                    "snippet": r["snippet"],
                }
            )

        return jsonify({"total": total, "page": page, "page_size": page_size, "items": items})

    return app


def _build_fts_query(q: str) -> tuple[str, list]:
    # Field scoping compatibility: map title:, speaker: to FTS columns
    tokens = q or ""
    tokens = tokens.replace("title:", "title:")
    tokens = tokens.replace("speaker:", "speaker_name:")
    tokens = tokens.replace("text:", "text:")
    if not tokens:
        tokens = '""'  # empty -> match nothing
    return tokens, []

def _fmt(s: int) -> str:
    s = int(s or 0)
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    return f"{h:02d}:{m:02d}:{ss:02d}"


def main():
    parser = argparse.ArgumentParser(description="Standalone Factbase Web UI")
    parser.add_argument("--db", default="out/transcripts.db", help="SQLite DB path")
    parser.add_argument("--host", default="0.0.0.0", help="Host")
    parser.add_argument("--port", type=int, default=5173, help="Port")
    args = parser.parse_args()

    conn = connect(args.db)
    init_db(conn)
    app = create_app(conn)
    app.run(host=args.host, port=args.port)


if __name__ == "__main__":
    main()
