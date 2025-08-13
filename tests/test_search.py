import sqlite3

from factbase.db import init_db


def load_sample(conn: sqlite3.Connection):
    init_db(conn)
    conn.execute(
        "INSERT INTO transcripts (id, url, title, date, duration_seconds, full_text, raw_html, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))",
        (
            "t1",
            "https://rollcall.com/factbase/trump/transcript/t1",
            "Donald Trump Press Conference",
            "2023-05-01",
            20,
            "Well, thank you very much everyone. immigration policies.",
            "",
        ),
    )
    conn.executemany(
        """
        INSERT INTO segments (transcript_id, speaker_name, speaker_id, start_time, end_time, duration, text, sentiment_score, segment_order)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("t1", "Donald Trump", "dt", 0, 5, 5, "Well, thank you very much everyone.", None, 1),
            ("t1", "Reporter", "rp", 5, 10, 5, "Mr. President, about immigration?", None, 2),
            ("t1", "Donald Trump", "dt", 10, 20, 10, "We are working on strong immigration policies.", None, 3),
        ],
    )
    conn.execute(
        "INSERT INTO speakers (transcript_id, name, speaker_id, sentences, words, seconds, percentage) VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("t1", "Donald Trump", "dt", 2, 10, 15, 75.0),
    )
    conn.commit()


def fts_query(conn: sqlite3.Connection, q: str):
    sql = (
        "SELECT transcripts.id, snippet(segments_fts, 0, '<mark>', '</mark>', ' … ', 10) as snip "
        "FROM segments_fts JOIN segments ON segments.id=segments_fts.rowid "
        "JOIN transcripts ON transcripts.id=segments.transcript_id "
        "WHERE segments_fts MATCH ?"
    )
    return [tuple(r) for r in conn.execute(sql, (q,))]


def test_phrase_and_prefix():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    load_sample(conn)
    res = fts_query(conn, '"press conference" OR text:immigra*')
    assert any(r[0] == "t1" for r in res)


def test_field_scoped_and_boolean():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    load_sample(conn)
    # title scoped and NOT condition
    res = fts_query(conn, 'title:"donald trump" AND NOT text:"unrelated"')
    assert any(r[0] == "t1" for r in res)
    # speaker scoped
    res2 = fts_query(conn, 'speaker_name:"Reporter"')
    assert any(r[0] == "t1" for r in res2)

