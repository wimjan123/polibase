from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

import typer
from flask import Flask

from . import __version__
from .config import Config
from .db import connect, init_db
from .discovery import discover_urls
from .exporter import export_all
from .logging_utils import setup_logging
from .scraper import scrape_all
from .webapp import create_app


app = typer.Typer(help="Factbase transcripts tool")


def _cfg(out: Optional[str] = None, state: Optional[str] = None, debug: bool = False) -> Config:
    cfg = Config()
    if out:
        cfg.out_dir = out
    if state:
        cfg.state_dir = state
    if debug:
        cfg.debug = True
    setup_logging(cfg.logs_dir, cfg.debug)
    return cfg


# Commented out problematic version callback
# @app.callback()
# def version_callback(version: bool = typer.Option(False, "--version", help="Show version and exit", is_eager=True)):
#     if version:
#         typer.echo(f"factbase-tool {__version__}")
#         raise typer.Exit()


@app.command()
def discover(
    speakers: str = typer.Option("trump,biden,harris", help="Comma-separated speaker names"),
    max_items: int = typer.Option(10000, help="Max discovered items"),
    out: str = typer.Option("out", help="Output directory"),
    state: str = typer.Option("state", help="State directory"),
    debug: bool = typer.Option(False, help="Debug logging"),
    headless: bool = typer.Option(True, help="Headless browser"),
):
    """Discover transcript detail URLs and write out/discovered_urls.jsonl"""
    cfg = _cfg(out, state, debug)
    speaker_list = [s.strip() for s in speakers.split(",") if s.strip()]
    urls = discover_urls(out_dir=cfg.out_dir, state_dir=cfg.state_dir, max_items=max_items, headless=headless, speakers=speaker_list)
    typer.echo(f"Discovered {len(urls)} URLs -> {os.path.join(cfg.out_dir, 'discovered_urls.jsonl')}")


@app.command()
def scrape(
    out: str = typer.Option("out", help="Output directory"),
    state: str = typer.Option("state", help="State directory"),
    db: str = typer.Option("out/transcripts.db", help="SQLite DB path"),
    rps: float = typer.Option(1.0, help="Requests per second"),
    concurrency: int = typer.Option(4, help="Concurrent workers"),
    debug: bool = typer.Option(False, help="Debug logging"),
):
    cfg = _cfg(out, state, debug)
    cfg.rps = rps
    cfg.concurrency = concurrency
    discovered_jsonl = os.path.join(cfg.out_dir, "discovered_urls.jsonl")
    stats = asyncio.run(scrape_all(cfg, db, discovered_jsonl))
    typer.echo(json.dumps({"summary": stats}))


@app.command()
def export(
    db: str = typer.Option("out/transcripts.db", help="SQLite DB path"),
    out: str = typer.Option("out", help="Output directory"),
):
    conn = connect(db)
    init_db(conn)
    export_all(conn, out)
    typer.echo("Exports written to out/")


@app.command()
def reimport(
    db: str = typer.Option("out/transcripts.db", help="SQLite DB path"),
    out: str = typer.Option("out", help="Output directory"),
    batch_size: int = typer.Option(50, help="Batch size for commits"),
    debug: bool = typer.Option(False, help="Debug logging"),
):
    """Re-import existing HTML files that are missing from the database."""
    from datetime import datetime
    from .parser import extract_transcript
    from .db import bulk_insert_segments, replace_entities, replace_speakers, replace_topics, upsert_transcript

    cfg = _cfg(out, None, debug)
    logger = logging.getLogger(__name__)

    html_dir = os.path.join(out, "html")
    if not os.path.exists(html_dir):
        typer.echo(f"No HTML directory found at {html_dir}")
        return

    conn = connect(db)
    init_db(conn)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")

    # Get existing IDs
    cur = conn.cursor()
    cur.execute("SELECT id FROM transcripts")
    existing_ids = set(r[0] for r in cur.fetchall())

    # Find HTML files
    html_files = [f for f in os.listdir(html_dir) if f.endswith('.html')]
    missing_files = [f for f in html_files if f.replace('.html', '') not in existing_ids]

    typer.echo(f"Found {len(html_files)} HTML files, {len(existing_ids)} in DB, {len(missing_files)} missing")

    if not missing_files:
        typer.echo("Nothing to reimport")
        return

    imported = 0
    failed = 0
    batch = []

    for i, filename in enumerate(missing_files):
        try:
            html_path = os.path.join(html_dir, filename)
            transcript_id = filename.replace('.html', '')

            # Reconstruct URL from ID
            # Try to detect person from ID
            if transcript_id.startswith('donald-trump'):
                person = 'trump'
            elif transcript_id.startswith('joe-biden'):
                person = 'biden'
            elif transcript_id.startswith('kamala-harris'):
                person = 'harris'
            else:
                person = 'trump'  # default

            url = f"https://rollcall.com/factbase/{person}/transcript/{transcript_id}"

            with open(html_path, 'r', encoding='utf-8') as f:
                html = f.read()

            data = extract_transcript(html, url)

            t = {
                "id": data["id"],
                "url": data["url"],
                "title": data.get("title"),
                "date": data.get("date"),
                "duration_seconds": data.get("duration_seconds"),
                "full_text": data.get("full_text"),
                "raw_html": html,
                "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }

            batch.append((t, data))

            if len(batch) >= batch_size:
                _flush_batch(conn, batch)
                imported += len(batch)
                batch = []
                typer.echo(f"Progress: {imported}/{len(missing_files)} imported")

        except Exception as e:
            logger.exception(f"Failed to reimport {filename}: {e}")
            failed += 1

    # Flush remaining
    if batch:
        _flush_batch(conn, batch)
        imported += len(batch)

    conn.close()
    typer.echo(f"Reimport complete: {imported} imported, {failed} failed")


def _flush_batch(conn, batch):
    """Flush a batch of transcripts to the database."""
    from .db import bulk_insert_segments, replace_entities, replace_speakers, replace_topics, upsert_transcript

    for t, data in batch:
        upsert_transcript(conn, t)
        conn.execute("DELETE FROM segments WHERE transcript_id=?", (t["id"],))
        bulk_insert_segments(conn, t["id"], data.get("segments", []))
        replace_speakers(conn, t["id"], data.get("speakers", []))
        replace_topics(conn, t["id"], [{"topic": x, "score": None} for x in data.get("topics", [])])
        replace_entities(conn, t["id"], data.get("entities", []))
    conn.commit()


@app.command()
def web(
    db: str = typer.Option("out/transcripts.db", help="SQLite DB path"),
    host: str = typer.Option("0.0.0.0", help="Host"),
    port: int = typer.Option(5000, help="Port"),
):
    conn = connect(db)
    init_db(conn)
    application: Flask = create_app(conn)
    application.run(host=host, port=port)


@app.command()
def run(
    speakers: str = typer.Option("trump,biden,harris", help="Comma-separated speaker names"),
    max_items: int = typer.Option(10000, help="Max discover items"),
    out: str = typer.Option("out", help="Output dir"),
    state: str = typer.Option("state", help="State dir"),
    db: str = typer.Option("out/transcripts.db", help="DB path"),
    host: str = typer.Option("0.0.0.0", help="Web host"),
    port: int = typer.Option(5000, help="Web port"),
    rps: float = typer.Option(1.0, help="Requests/sec"),
    concurrency: int = typer.Option(4, help="Concurrency"),
    debug: bool = typer.Option(False, help="Debug"),
):
    cfg = _cfg(out, state, debug)
    cfg.rps = rps
    cfg.concurrency = concurrency
    cfg.host = host
    cfg.port = port
    # Discover
    speaker_list = [s.strip() for s in speakers.split(",") if s.strip()]
    discover_urls(out_dir=cfg.out_dir, state_dir=cfg.state_dir, max_items=max_items, headless=True, speakers=speaker_list)
    # Scrape
    discovered_jsonl = os.path.join(cfg.out_dir, "discovered_urls.jsonl")
    asyncio.run(scrape_all(cfg, db, discovered_jsonl))
    # Export
    conn = connect(db)
    init_db(conn)
    export_all(conn, out)
    # Web
    application: Flask = create_app(conn)
    url = f"http://{cfg.host}:{cfg.port}"
    try:
        application.run(host=cfg.host, port=cfg.port)
    except Exception:
        typer.echo(f"Web UI at {url}")


if __name__ == "__main__":
    app()
