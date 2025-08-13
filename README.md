Factbase Roll Call Transcripts Scraper and Search UI

This project discovers, scrapes, indexes, and searches Roll Call Factba.se transcripts. It provides a CLI, SQLite storage with FTS5, JSON/CSV exports, and a minimal Web UI.

Quickstart

- Create venv, install deps, and browsers: `sh scripts/install.sh`
- Discover transcript URLs (headless): `sh scripts/discover.sh`
- Scrape and build the database: `sh scripts/scrape.sh`
- Export JSONL and CSV: `sh scripts/export.sh`
- Serve the Web UI at http://localhost:5000 (listens on all interfaces): `sh scripts/web.sh`
- End-to-end: `sh scripts/run.sh`
- Run tests: `sh scripts/test.sh`

Configuration

- Defaults: `host=0.0.0.0` (all interfaces), `port=5000`, `out=./out`, `state=./state`, `rps=1.0`, `concurrency=4`.
- Flags or env vars: `FACTBASE_HOST`, `FACTBASE_PORT`, `FACTBASE_OUT`, `FACTBASE_STATE`.
 
External Access

- The server now binds to `0.0.0.0:5000` by default so it’s reachable from other machines on your network. If you prefer local-only, run with `--host 127.0.0.1` or set `FACTBASE_HOST=127.0.0.1`.
- Ensure your OS firewall allows inbound TCP 5000. Examples:
  - UFW (Ubuntu): `sudo ufw allow 5000/tcp`
  - Firewalld (RHEL/Fedora): `sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload`
- Access over SSH without opening firewall:
  - Local forward: `ssh -L 5000:127.0.0.1:5000 user@server` then browse `http://localhost:5000` on your machine.
  - Remote forward: `ssh -R 5000:127.0.0.1:5000 user@server` if you need the reverse direction.


Discovery Troubleshooting

- Cookie/consent walls are auto-accepted. Infinite scroll is handled; observed endpoints are persisted to `state/endpoints.json`.
- If zero results are found, the DOM is saved to `out/listing_dump.html`.

Search Syntax

- Phrases: `"press conference"`
- Boolean: `immigration AND NOT title:"press pool"`
- Prefix: `immigra*`
- Field scoping: `speaker:"Donald Trump" immigration` and `text:immigra*`

Examples

- `"press conference"`
- `speaker:"Donald Trump" immigration`
- `text:immigra* AND NOT title:"press pool"`

Known Limitations

- Site structure may change; parser is robust but not guaranteed.
- Sentiment not computed.
- Topics/entities included only if present.
- Playwright downloads Chromium during install.
