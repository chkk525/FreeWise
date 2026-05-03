# FreeWise (chkk525 fork)

[![Tests: 840 passing](https://img.shields.io/badge/tests-840%20passing-brightgreen)](#running-tests)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: CC0](https://img.shields.io/badge/license-CC0-green)
![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![PWA](https://img.shields.io/badge/PWA-installable-purple?logo=pwa)

> Self-hosted highlight library — Readwise's daily-review + ask-anything
> experience without the subscription, the data sale, or the lock-in.

This is a **fork** of [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise).
The upstream provides a clean FastAPI + HTMX baseline (CRUD, import/export,
review, dashboard). This fork adds full-text search, semantic search,
Retrieval-Augmented Generation (RAG) over your library, a Kindle scraper
pipeline, an SMTP email digest, an OG image generator, a CLI, an MCP
stdio server with 30 tools, and more — all single-user, single-binary,
SQLite-backed.

> [!TIP]
> For the day-to-day reference of every CLI command / API endpoint /
> MCP tool, see [`docs/USAGE.md`](docs/USAGE.md). For the timeline of
> what's been added, see [`CHANGELOG.md`](CHANGELOG.md).

---

## Highlights of the fork

### Search & discovery

- **FTS5 trigram full-text search** — works for English, Japanese,
  Chinese without MeCab. Auto-backfills on first start; LIKE fallback
  if FTS5 isn't compiled in.
- **Faceted search** — `?favorited_only=true&has_note=true&tag=ml` on
  `/highlights/ui/search`. Filter-only browsing valid (no `q` required).
- **Author index** at `/library/ui/authors` with sort tabs.
- **Per-tag detail page** at `/highlights/ui/tag/{name}`.
- **On-this-day** dashboard widget — past-year highlights for today's MM-DD.
- **Daily-pick** widget — deterministic highlight of the day.

### AI / RAG (Ollama-backed)

- **Embedding substrate** — per-highlight vectors, cosine retrieval,
  chunked numpy matmul (handles 25k×768 in ~50ms).
- **`/ask` endpoint** + UI page — answers questions over the library
  with citation links to the source highlights.
- **Per-book summarize** — LLM summary using only that book's highlights.
- **Tag suggestions** — embedding-neighbor-based for one highlight.
- **Semantic near-duplicate detection** + UI page with one-click discard.

### Curation & cleanup

- **Exact duplicate finder** with bulk-cleanup UI.
- **Library-health card** on dashboard — surfaces dup-group count and
  tagging-coverage % with backfill CTAs (defer-loaded so the main
  page returns instantly).
- **Tag rename / merge / autocomplete** — bulk operations + native
  `<datalist>` suggestions on the bulk-tag input.
- **Author rename** across all books.
- **Append-to-note** — atomic concat with 8191-char cap.
- **Quick-capture** dashboard textarea.
- **Copy-as-quote** button on every highlight row.
- **Notes formatting** — preserves line breaks and auto-links bare URLs
  (XSS-safe; `javascript:`/`data:` schemes rejected).

### Sharing

- **Open Graph + Twitter Card meta** on every highlight permalink.
- **Quote-card OG image** at `/highlights/ui/h/{id}/quote.png` —
  1200×630 PNG with the highlight + author/title attribution. Twitter,
  Slack, iMessage all expand richly.

### Import / export

- **Multi-format import** — Readwise CSV, Kindle JSON, Meebook HTML,
  custom CSV. CLI auto-detects by extension.
- **Kindle scraper pipeline** (separate `freewise-qnap-kindle` repo) —
  Playwright headless scrape of `read.amazon.com`, dedup-by-ASIN,
  webhook notifications, daily cron schedule. **"Scrape now" button**
  on the dashboard for on-demand triggers.
- **Filtered export** — `?tag=…&book_id=…&author=…&favorited_only=true&active_only=true`
  on `/export/csv` and `/export/markdown.zip`.
- **Markdown export** — Obsidian / Logseq friendly, one `.md` per book.

### Operations

- **`/healthz`** — counts + Ollama reachability.
- **`/metrics`** — Prometheus exposition (7 gauges: highlights_total /
  active / favorited / mastered, books_total, embeddings_count +
  embedding_coverage, freewise_up).
- **`/api/v2/admin/backup`** — atomic SQLite snapshot via
  `sqlite3.backup()`. Token-gated, dedicated 3 req/IP/min rate bucket.
- **CLI backup rotation** — `freewise backup --to-dir DIR --retain N`
  for cron, ms-precision timestamps.
- **Daily email digest** — SMTP via env vars. POST `/api/v2/admin/digest/send`
  or `freewise digest --send`. Subject + HTML body include today's
  pick, on-this-day highlights, and library-health summary.
- **Per-IP rate limiter** + security headers + hashed API tokens.

### Multi-surface

- **`freewise` CLI** — 36+ subcommands (search, today, ask, backup,
  digest, import, …). One binary, one auth file.
- **MCP stdio server** — 30 tools so a Claude Code session has
  first-class read/write access to the library:
  `freewise_search`, `freewise_ask`, `freewise_summarize_book`,
  `freewise_today`, `freewise_backup`, `freewise_health`, etc.

### Engineering

- **Test coverage:** 840 passing (server 767 + CLI 42 + MCP 31).
- **Code review at every batch boundary** — U57, U67, U75, U79, U83,
  U92, U100. Every CRITICAL / HIGH cleared before the next batch starts.
- **Defer-load HTMX pattern** — heavy dashboard widgets (full-table
  scans) load after the main page returns.
- **Forward-only schema migrations** — no alembic, just `app/db.py`
  inspecting `PRAGMA table_info` and adding columns idempotently.

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | [FastAPI](https://fastapi.tiangolo.com/) + [SQLModel](https://sqlmodel.tiangolo.com/) |
| Database | SQLite + FTS5 (trigram tokenizer) |
| Frontend | [HTMX](https://htmx.org/) + [TailwindCSS](https://tailwindcss.com/) + [Lucide Icons](https://lucide.dev/) |
| Templating | Jinja2 (with custom `autolink` filter for note rendering) |
| AI | [Ollama](https://ollama.com) (`nomic-embed-text` for embeddings, `llama3.2` for generation) |
| Image | [Pillow](https://pillow.readthedocs.io) for the OG quote-card |
| Container | Docker + Docker Compose |
| MCP | [`mcp`](https://pypi.org/project/mcp/) (FastMCP) over stdio |

---

## Quick Start

> **Requirements:** [Docker](https://docs.docker.com/get-docker/) and
> [Docker Compose](https://docs.docker.com/compose/install/).

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise
docker compose up -d --build
```

Open **http://localhost:8063** in your browser.

The first build takes ~2 minutes (Node CSS compile + Pillow build).
Subsequent starts are instant. On first start the FTS5 index
auto-backfills (a few seconds for 25k rows).

### Optional: enable AI features

`docker-compose.yml` already defines an Ollama service. Pull models once:

```bash
docker compose exec ollama ollama pull nomic-embed-text
docker compose exec ollama ollama pull llama3.2
```

Then visit `/dashboard/ui` and use the **"Embed all"** action, or run
`freewise embed-backfill`. See [`docs/SEMANTIC_SETUP.md`](docs/SEMANTIC_SETUP.md).

### Optional: enable email digest

Add to `.env` (or `.env.qnap`, both gitignored):

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<Gmail App Password — spaces ok>
SMTP_FROM=FreeWise <you@gmail.com>
SMTP_TO=you@gmail.com
```

Test: `freewise digest` (dry-run preview). Send: `freewise digest --send`.
Cron: `0 8 * * * freewise digest --send`.

### Optional: enable Kindle scrape-now button

Set `KINDLE_SCRAPE_CMD` to your scrape entry point (typically
`/srv/freewise/kindle/tools/kindle_dl.sh` from the
[`freewise-qnap-kindle`](https://github.com/chkk525/freewise-qnap-kindle)
sibling repo). The dashboard button appears automatically.

---

## CLI

```bash
pip install -e cli/
freewise auth login --url https://your-host --token <api-token>
freewise search "stoicism"
freewise today
freewise ask "what did I learn about systems thinking?"
freewise backup --to-dir /backups --retain 7
freewise digest --send
```

36+ subcommands — see [`docs/USAGE.md`](docs/USAGE.md) for the full list.

---

## MCP

Add to your Claude Code settings:

```json
{
  "mcpServers": {
    "freewise": {
      "command": "python",
      "args": ["-m", "freewise_mcp.server"],
      "env": {
        "FREEWISE_URL": "https://your-host",
        "FREEWISE_TOKEN": "<api-token>"
      }
    }
  }
}
```

Restart Claude Code. The 30 `freewise_*` tools become available in any
conversation.

---

## Docker Reference

### Common commands

| Task | Command |
|---|---|
| Start (first time or after update) | `docker compose up -d --build` |
| Start (no rebuild) | `docker compose up -d` |
| Stop (data preserved) | `docker compose down` |
| Stop and wipe all data | `docker compose down -v` |
| Follow logs | `docker compose logs -f` |
| Restart the container | `docker compose restart freewise` |

### Updating to a newer version

```bash
git pull
docker compose up -d --build
```

The schema migrations (incl. FTS5 backfill) run automatically on
first startup post-upgrade.

### Data persistence

| Volume | Mount path | Contents |
|---|---|---|
| `freewise-db` | `/srv/freewise/db` | SQLite database (incl. FTS5 index, embeddings) |
| `freewise-covers` | `/srv/freewise/app/static/uploads/covers` | Uploaded book cover images |

### Backing up your data

The cleanest path is the in-app backup endpoint (atomic via
`sqlite3.backup()`):

```bash
freewise backup --to-dir ./backups --retain 7
```

Or via raw `curl`:

```bash
curl -H "Authorization: Token $FREEWISE_TOKEN" \
  https://your-host/api/v2/admin/backup -o freewise-$(date +%F).sqlite
```

The Docker volume tarball approach still works as a fallback:

```bash
docker run --rm \
  -v freewise-db:/data \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/freewise-db-backup.tar.gz -C /data .
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `FREEWISE_DB_URL` | `sqlite:///./db/freewise.db` | SQLAlchemy database URL |
| `FREEWISE_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL |
| `FREEWISE_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model |
| `FREEWISE_OLLAMA_GENERATE_MODEL` | `llama3.2` | Chat / generate model |
| `FREEWISE_KINDLE_WATCH_DIR` | unset | Auto-import watcher target dir |
| `FREEWISE_KINDLE_NOTIFY_URL` | unset | Webhook for import outcome |
| `KINDLE_SCRAPE_CMD` | unset | "Scrape now" button command (hidden when unset) |
| `KINDLE_SCRAPE_STATE_FILE` | `/tmp/freewise-kindle-scrape.json` | Trigger state |
| `SMTP_HOST` / `SMTP_PORT` / `SMTP_USER` / `SMTP_PASS` / `SMTP_FROM` / `SMTP_TO` | unset | Email digest config (digest disabled when any unset) |

---

## Local Development

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise

uv sync                          # creates .venv with all deps
uv run uvicorn app.main:app --reload

# In another shell — for Tailwind:
npm install && npm run build:css
```

The application will be available at **http://localhost:8000**.

### Running tests

```bash
uv run pytest                    # server suite (767 tests)
uv run pytest cli/tests/         # CLI suite (42 tests)
uv run pytest mcp/tests/         # MCP suite (31 tests)
```

CLI and MCP test trees can't be collected together with the server
tests because they each set up their own in-process FastAPI app.

---

## Project Structure

```
app/
├── main.py                       # FastAPI entry point
├── db.py                         # Engine + forward-only migrations + FTS5 setup
├── models.py                     # SQLModel ORM models
├── api_v2/                       # Token-gated /api/v2/* endpoints
├── importers/                    # Import pipelines (Kindle JSON, Readwise CSV, …)
├── middleware/                   # Custom Starlette middleware (gzip request body)
├── routers/                      # HTML routes (dashboard, library, highlights, …)
├── services/                     # Embeddings, RAG, digest, email, quote_card, kindle_*
├── template_filters.py           # Custom Jinja filters (autolink + make_templates helper)
├── templates/                    # Jinja2 HTML
└── static/                       # CSS, JS, uploaded covers
cli/                              # `freewise` CLI (separate package)
mcp/                              # MCP stdio server with 30 tools
extensions/
└── kindle-importer/              # Chrome MV3 extension — see docs/KINDLE_BROWSER_EXTENSION.md
scrapers/
└── kindle/                       # Playwright fallback scraper (monthly cron on QNAP)
shared/                           # Selectors + JSON Schema shared by Python + TS
docs/
├── USAGE.md                      # Reference for every CLI cmd / API endpoint / MCP tool
├── SEMANTIC_SETUP.md             # Ollama install + first-time backfill
├── KINDLE_JSON_SCHEMA.md         # Contract with the Kindle scraper
├── KINDLE_BROWSER_EXTENSION.md   # MV3 extension architecture, install, error matrix
└── …
tests/                            # pytest suite (server)
CHANGELOG.md                      # Theme-grouped changelog of fork additions
Dockerfile                        # Multi-stage Node → Python production image
docker-compose.yml                # Single-service deployment
```

---

## Roadmap

- [ ] Notion integration for "currently reading" sync
- [ ] PDF / EPUB attachment view
- [ ] Differential Kindle scrape (only changed books)
- [ ] PWA full offline mode

---

## Acknowledgements

Built on top of [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise).
The original CRUD / import / review baseline is unchanged; this fork
adds the search / AI / multi-surface / ops layers on top.

This fork is intentionally single-user — it stays a personal tool, not
a hosted service. Do **not** PR upstream from this branch.

---

## License

[CC0](LICENSE) — same as upstream.
