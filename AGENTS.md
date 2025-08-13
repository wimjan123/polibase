# Repository Guidelines

## Project Structure & Modules
- `factbase/`: Python package (CLI, scraping, parsing, DB, web UI)
  - `cli.py`, `discovery.py`, `scraper.py`, `parser.py`, `db.py`, `exporter.py`, `webapp.py`, `utils.py`, `config.py`, `logging_utils.py`.
- `tests/`: Pytest suite and fixtures (e.g., `tests/test_parse.py`, `tests/fixtures/…`).
- `scripts/`: Task runners for local dev (install, discover, scrape, export, web, test).
- `static/`: Minimal web UI assets served by Flask.
- `out/`, `state/`, `logs/`: Runtime artifacts and cache; safe to delete.

## Build, Test, and Dev Commands
- Create venv and install: `sh scripts/install.sh` (editable install + Playwright browsers).
- Discover URLs: `sh scripts/discover.sh [out [start_url]]`.
- Scrape and build DB: `sh scripts/scrape.sh [out [out/transcripts.db]]`.
- Export JSONL/CSV: `sh scripts/export.sh [out [out/transcripts.db]]`.
- Run web UI: `sh scripts/web.sh [out/transcripts.db [host [port]]]`.
- End‑to‑end: `sh scripts/run.sh` (discover → scrape → export → web).
- Tests: `sh scripts/test.sh` or `pytest -q`.
- Direct CLI usage: `factbase discover|scrape|export|web|run --help`.

## Coding Style & Naming
- Python 3.10+; follow PEP 8 with 4‑space indents.
- Modules/files: lowercase with underscores; functions `snake_case`, classes `CamelCase`.
- Prefer type hints and docstrings; avoid `print` in library code—use `logging_utils.setup_logging`.
- Keep CLI options mirrored in `Config` env vars (see below) and documented `--help`.

## Testing Guidelines
- Framework: Pytest. Place tests under `tests/` named `test_*.py`.
- Add focused unit tests for parsers, DB, and search; include fixtures in `tests/fixtures/`.
- Run locally with `pytest -q`; ensure new tests pass before PR.

## Commit & Pull Requests
- Commits: imperative, concise subject; include rationale in body if non‑trivial.
- PRs: clear description, linked issues, reproduction steps; screenshots for UI changes; note any schema changes or new env vars.
- Keep changes small and scoped; update README or scripts when behavior changes.

## Security & Configuration Tips
- Defaults: `FACTBASE_HOST=0.0.0.0`, `FACTBASE_PORT=5000`, `FACTBASE_OUT=out`, `FACTBASE_STATE=state`, `FACTBASE_LOGS=logs`, `FACTBASE_RPS`, `FACTBASE_CONCURRENCY`, `FACTBASE_DEBUG`.
- For local‑only web UI, use `factbase web --host 127.0.0.1` or set `FACTBASE_HOST=127.0.0.1`.
- If exposing externally, ensure firewall allows TCP 5000 or tunnel via SSH.
