from __future__ import annotations

import csv
import json
import os
import sqlite3


def export_all(conn: sqlite3.Connection, out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)

    # transcripts.jsonl
    with open(os.path.join(out_dir, "transcripts.jsonl"), "w", encoding="utf-8") as f:
        for row in conn.execute(
            "SELECT id, url, title, date, duration_seconds FROM transcripts ORDER BY date DESC NULLS LAST"
        ):
            f.write(json.dumps(dict(row)) + "\n")

    # segments.jsonl
    with open(os.path.join(out_dir, "segments.jsonl"), "w", encoding="utf-8") as f:
        for row in conn.execute(
            """
            SELECT id, transcript_id, speaker_name, speaker_id, start_time, end_time, duration, text, segment_order
            FROM segments
            ORDER BY transcript_id, segment_order
            """
        ):
            f.write(json.dumps(dict(row)) + "\n")

    # transcripts.csv
    with open(os.path.join(out_dir, "transcripts.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "url", "title", "date", "duration_seconds", "created_at"])
        for row in conn.execute(
            "SELECT id, url, title, date, duration_seconds, created_at FROM transcripts ORDER BY date DESC"
        ):
            w.writerow([row["id"], row["url"], row["title"], row["date"], row["duration_seconds"], row["created_at"]])

    # segments.csv
    with open(os.path.join(out_dir, "segments.csv"), "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "id",
            "transcript_id",
            "speaker_name",
            "speaker_id",
            "start_time",
            "end_time",
            "duration",
            "text",
            "segment_order",
        ])
        for row in conn.execute(
            """
            SELECT id, transcript_id, speaker_name, speaker_id, start_time, end_time, duration, text, segment_order
            FROM segments ORDER BY transcript_id, segment_order
            """
        ):
            w.writerow([
                row["id"],
                row["transcript_id"],
                row["speaker_name"],
                row["speaker_id"],
                row["start_time"],
                row["end_time"],
                row["duration"],
                row["text"],
                row["segment_order"],
            ])

