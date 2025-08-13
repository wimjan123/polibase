from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Iterable, Optional


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS transcripts (
            id TEXT PRIMARY KEY,
            url TEXT UNIQUE,
            title TEXT,
            date TEXT,
            duration_seconds INTEGER,
            full_text TEXT,
            raw_html TEXT,
            created_at TEXT
        );

        CREATE TABLE IF NOT EXISTS speakers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id TEXT REFERENCES transcripts(id) ON DELETE CASCADE,
            name TEXT,
            speaker_id TEXT,
            sentences INTEGER,
            words INTEGER,
            seconds INTEGER,
            percentage REAL
        );

        CREATE TABLE IF NOT EXISTS segments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id TEXT REFERENCES transcripts(id) ON DELETE CASCADE,
            speaker_name TEXT,
            speaker_id TEXT,
            start_time INTEGER,
            end_time INTEGER,
            duration INTEGER,
            text TEXT,
            sentiment_score REAL,
            segment_order INTEGER
        );

        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id TEXT REFERENCES transcripts(id) ON DELETE CASCADE,
            topic TEXT,
            score REAL
        );

        CREATE TABLE IF NOT EXISTS entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transcript_id TEXT REFERENCES transcripts(id) ON DELETE CASCADE,
            entity TEXT
        );

        -- FTS5 index for searching segments with speaker and title context
        CREATE VIRTUAL TABLE IF NOT EXISTS segments_fts USING fts5(
            text,
            speaker_name,
            speaker_id,
            title,
            transcript_id UNINDEXED,
            content='segments',
            content_rowid='id'
        );

        -- Triggers to sync FTS
        CREATE TRIGGER IF NOT EXISTS segments_ai AFTER INSERT ON segments BEGIN
            INSERT INTO segments_fts(rowid, text, speaker_name, speaker_id, title, transcript_id)
            SELECT new.id, new.text, new.speaker_name, new.speaker_id,
                   (SELECT title FROM transcripts WHERE id=new.transcript_id),
                   new.transcript_id;
        END;

        CREATE TRIGGER IF NOT EXISTS segments_ad AFTER DELETE ON segments BEGIN
            INSERT INTO segments_fts(segments_fts, rowid, text) VALUES('delete', old.id, old.text);
        END;

        CREATE TRIGGER IF NOT EXISTS segments_au AFTER UPDATE ON segments BEGIN
            INSERT INTO segments_fts(segments_fts) VALUES('rebuild');
        END;
        """
    )
    conn.commit()


def bulk_insert_segments(
    conn: sqlite3.Connection,
    transcript_id: str,
    segments: Iterable[dict],
) -> None:
    conn.executemany(
        """
        INSERT INTO segments (
            transcript_id, speaker_name, speaker_id, start_time, end_time,
            duration, text, sentiment_score, segment_order
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                transcript_id,
                s.get("speaker_name"),
                s.get("speaker_id"),
                s.get("start_time"),
                s.get("end_time"),
                s.get("duration"),
                s.get("text"),
                s.get("sentiment_score"),
                s.get("segment_order"),
            )
            for s in segments
        ],
    )
    conn.commit()


def upsert_transcript(
    conn: sqlite3.Connection,
    t: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO transcripts (id, url, title, date, duration_seconds, full_text, raw_html, created_at)
        VALUES (:id, :url, :title, :date, :duration_seconds, :full_text, :raw_html, :created_at)
        ON CONFLICT(id) DO UPDATE SET
            url=excluded.url,
            title=excluded.title,
            date=excluded.date,
            duration_seconds=excluded.duration_seconds,
            full_text=excluded.full_text,
            raw_html=excluded.raw_html
        """,
        t,
    )
    conn.commit()


def replace_speakers(conn: sqlite3.Connection, transcript_id: str, speakers: Iterable[dict]) -> None:
    conn.execute("DELETE FROM speakers WHERE transcript_id=?", (transcript_id,))
    conn.executemany(
        """
        INSERT INTO speakers (
            transcript_id, name, speaker_id, sentences, words, seconds, percentage
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                transcript_id,
                s.get("name"),
                s.get("speaker_id"),
                s.get("sentences", 0),
                s.get("words", 0),
                s.get("seconds", 0),
                s.get("percentage", 0.0),
            )
            for s in speakers
        ],
    )
    conn.commit()


def replace_topics(conn: sqlite3.Connection, transcript_id: str, topics: Iterable[dict]) -> None:
    conn.execute("DELETE FROM topics WHERE transcript_id=?", (transcript_id,))
    conn.executemany(
        "INSERT INTO topics (transcript_id, topic, score) VALUES (?, ?, ?)",
        [(transcript_id, t.get("topic"), t.get("score")) for t in topics],
    )
    conn.commit()


def replace_entities(conn: sqlite3.Connection, transcript_id: str, entities: Iterable[str]) -> None:
    conn.execute("DELETE FROM entities WHERE transcript_id=?", (transcript_id,))
    conn.executemany(
        "INSERT INTO entities (transcript_id, entity) VALUES (?, ?)",
        [(transcript_id, e) for e in entities],
    )
    conn.commit()


@contextmanager
def db_session(db_path: str):
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()

