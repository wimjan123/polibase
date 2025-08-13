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


@app.callback()
def version_callback(version: Optional[bool] = typer.Option(None, "--version", callback=None, help="Show version and exit", is_eager=True)):
    if version:
        typer.echo(f"factbase-tool {__version__}")
        raise typer.Exit()


@app.command()
def discover(
    start: str = typer.Option("https://rollcall.com/factbase/transcripts/", help="Listing start URL"),
    max_items: int = typer.Option(400, help="Max discovered items"),
    out: str = typer.Option("out", help="Output directory"),
    state: str = typer.Option("state", help="State directory"),
    debug: bool = typer.Option(False, help="Debug logging"),
    headless: bool = typer.Option(True, help="Headless browser"),
):
    """Discover transcript detail URLs and write out/discovered_urls.jsonl"""
    cfg = _cfg(out, state, debug)
    urls = discover_urls(start, cfg.out_dir, cfg.state_dir, max_items=max_items, headless=headless)
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
    start: str = typer.Option("https://rollcall.com/factbase/transcripts/", help="Start URL"),
    max_items: int = typer.Option(400, help="Max discover items"),
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
    discover_urls(start, cfg.out_dir, cfg.state_dir, max_items=max_items, headless=True)
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
