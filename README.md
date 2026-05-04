# FreeWise

[![Tests: 885 / 50 / 31 passing](https://img.shields.io/badge/tests-966%20passing-brightgreen)](#testing)
![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)
![License: CC0](https://img.shields.io/badge/license-CC0-green)
![Docker](https://img.shields.io/badge/docker-ready-blue?logo=docker)
![PWA](https://img.shields.io/badge/PWA-installable-purple?logo=pwa)
![MCP-ready](https://img.shields.io/badge/MCP-30%20tools-orange)

> **Self-hosted highlight library — own your reading the way Readwise *almost* lets you, without the subscription, the data sale, or the lock-in.**

FreeWise is the FastAPI + SQLite + HTMX clone of Readwise's daily-review experience, plus search, RAG ("ask my library"), Kindle scraping, an HTML+CLI+MCP triple surface, and a Chrome extension that turns any web selection into a saved highlight. **Single user, single binary, single SQLite file** — designed to run on your laptop, a $50 VPS, or a NAS.

This repo is the [`chkk525`](https://github.com/chkk525) **fork** of [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise). The upstream is the CRUD/import/review baseline; this fork adds everything documented under [What's in this fork](#whats-in-this-fork) below. **PRs stay on the fork — never opened upstream.**

---

## Table of contents

1. [Who is this for?](#who-is-this-for)
2. [Quick start (3 commands)](#quick-start-3-commands)
3. [What's in this fork](#whats-in-this-fork)
4. [Tour of the surfaces](#tour-of-the-surfaces)
   - [Web UI](#web-ui)
   - [REST API (`/api/v2`)](#rest-api-apiv2)
   - [`freewise` CLI](#freewise-cli)
   - [`freewise-mcp` MCP server](#freewise-mcp-mcp-server)
   - [Chrome extension](#chrome-extension)
5. [Configuration reference](#configuration-reference)
6. [Operations](#operations)
7. [Development](#development)
8. [Troubleshooting](#troubleshooting)
9. [Roadmap](#roadmap)
10. [Contributing](#contributing)
11. [License](#license)

---

## Who is this for?

| You are… | …and FreeWise gives you |
|---|---|
| A heavy reader of books, articles, papers | A searchable, taggable, **permanent** home for the highlights you'll otherwise lose. |
| A Readwise subscriber tired of paying $8/mo | The same daily-review loop, FTS5 search, OG image cards, and email digest — self-hosted, in one Docker container. |
| A Claude Code / LLM tinkerer | A **30-tool MCP server** so the assistant can read, write, and reason over your library directly. |
| A privacy-leaning reader | All embeddings, all search, all LLM RAG runs locally via Ollama. No third party sees your highlights. |
| A Kindle reader who hates web-based exports | A Chrome extension + a Playwright scraper + a manual import path — three ways to get notes out, all idempotent. |

**Not for you if** you need: real-time multi-device sync, multi-user permissions, a hosted SaaS UI, or a free-tier mobile app. FreeWise is intentionally single-user and single-tenant.

---

## Quick start (3 commands)

> **Requirements:** [Docker](https://docs.docker.com/get-docker/) + [Docker Compose](https://docs.docker.com/compose/install/). Tested on Linux, macOS, and QNAP Container Station.

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise
docker compose up -d --build
```

→ Open **http://localhost:8063** and you'll see an empty dashboard.

**Success criteria:** by the end of the next 5 minutes you should have

1. ✅ Imported your existing highlights (Readwise CSV, Kindle JSON, or use the Chrome extension live).
2. ✅ Searched for one of them by Japanese / English / mixed-script substring.
3. ✅ Bookmarked one as a favorite from the dashboard's daily review card.

If anything fails, jump to [Troubleshooting](#troubleshooting).

### Optional: enable AI features

```bash
docker compose exec ollama ollama pull nomic-embed-text  # embeddings
docker compose exec ollama ollama pull llama3.2          # chat / RAG
```

Then run `freewise embed-backfill` once to vectorize the library. After that, `/highlights/ui/ask` and the related-highlights surface light up.

### Optional: enable email digest

Add SMTP creds to `.env`:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASS=<Gmail App Password>
SMTP_FROM=FreeWise <you@gmail.com>
SMTP_TO=you@gmail.com
```

Test once: `freewise digest` (dry-run preview). Then schedule:

```cron
0 8 * * *  freewise digest --send
```

---

## What's in this fork

Grouped by user job-to-be-done. The upstream `wardeiling/FreeWise` ships the CRUD baseline; everything below is fork-only.

### 1. Find anything you've ever read

- **FTS5 trigram search** — works for English, 日本語, 中文, mixed-script, no MeCab needed. Auto-backfills on first start; LIKE fallback if FTS5 isn't compiled in.
- **Result snippets with `<mark>` highlighting** at `/highlights/ui/search` and `/api/v2/highlights/search` — sentinel-then-escape XSS-safe rendering.
- **Faceted search** — combine `?q=` + `?tag=` + `?favorited_only=true` + `?has_note=true`. Filter-only browsing valid (no query needed).
- **Author / tag / book pivots** — every highlight links into the author index, tag detail, and book detail pages.

### 2. Get into a daily review habit

- **Daily review card** with weighted random pick (favors fresh, low-mastery highlights).
- **Streak counter** + 30-day GitHub-style heatmap on the dashboard.
- **Daily digest page** at `/digest/today` — same picks all day; refreshes once at midnight.
- **Activity timeline** at `/highlights/ui/activity` — newest-first log of every favorite/discard/master action, grouped by date, filterable by verb.
- **Cold-books re-engagement widget** on the dashboard — surfaces 5 books you haven't touched in the longest time, so the long-tail of imports doesn't rot.

### 3. Ask your library questions (RAG)

- **Embedding substrate** — per-highlight `nomic-embed-text` vectors, cosine retrieval, chunked numpy matmul (handles 25k × 768 in ~50ms).
- **`/highlights/ui/ask`** — answers questions over the library with citation links to the source highlights.
- **Per-book summarize** — LLM summary using only that book's highlights, available from book detail pages.
- **Tag suggestions** — embedding-neighbor based, accepts/rejects via HTMX.
- **Semantic near-duplicate detection** + UI page with one-click discard.
- **Related highlights** at `/highlights/ui/h/{id}/related` — top-K cosine-similar items.

### 4. Import & curate

- **Multi-format import** — Readwise CSV, Kindle JSON (the Amazon export shape), Meebook HTML, custom CSV. CLI auto-detects by extension.
- **Kindle scraper pipeline** — Playwright headless scrape of `read.amazon.com`, dedup-by-ASIN, webhook notifications, daily cron schedule. **"Scrape now" button** on the dashboard for on-demand triggers (lives in the [`freewise-qnap-kindle`](https://github.com/chkk525/freewise-qnap-kindle) sibling repo).
- **Chrome extension** — right-click any web selection → save to `/api/v2/highlights/`. MV3, persistent storage, recent-saves history. See [Chrome extension](#chrome-extension).
- **Tag rename / merge / autocomplete** — bulk operations + native `<datalist>` suggestions.
- **Author rename across all books** — fixes typos and full-width-space splits in one shot.
- **Append-to-note** — atomic concat with 8191-char cap.
- **Quick-capture textarea** on the dashboard.
- **Exact + semantic duplicate finder** with bulk-cleanup UI.

### 5. Share what you've highlighted

- **Open Graph + Twitter Card meta** on every highlight permalink → rich previews in Slack, iMessage, Twitter.
- **Quote-card OG image** at `/highlights/ui/h/{id}/quote.png` — 1200×630 PNG with attribution, generated on demand via Pillow.
- **Filtered export** — `?tag=…&book_id=…&author=…&favorited_only=true&active_only=true` on `/export/csv` and `/export/markdown.zip`.
- **Markdown export** — Obsidian / Logseq / Notion-flavored, one `.md` per book, atomic-notes mode for Zettelkasten workflows.

### 6. Operate without surprise

- **`/healthz`** — counts + Ollama reachability.
- **`/metrics`** — Prometheus exposition (7 gauges).
- **Atomic SQLite backup** via `sqlite3.backup()` — token-gated `/api/v2/admin/backup` and `freewise backup --to-dir DIR --retain N` for cron rotation.
- **Per-IP rate limiter**, **security headers**, **hashed API tokens** with token-prefix display.
- **Forward-only migrations** — no Alembic, just `app/db.py` doing `PRAGMA table_info` introspection + idempotent column adds + table-rebuild for SQLite-can't-DROP-NOT-NULL cases.
- **Defer-loaded HTMX widgets** — heavy dashboard widgets (dup-group scan, tagging-coverage, on-this-day) load after the main page returns.

### 7. Multi-surface from day one

| Surface | What you get | How to drive it |
|---|---|---|
| **Web UI** | Daily review, dashboard, library, search, activity, ask, settings | Browser at `:8063` |
| **REST API** | Token-authed `/api/v2` (Readwise-shaped where it makes sense) | `Authorization: Token <raw>` |
| **CLI** | 32 subcommands across read, write, discovery, RAG, ops | `freewise <cmd>` |
| **MCP** | 30 tools so Claude Code / Claude Desktop reads & writes the library | stdio adapter |
| **Chrome extension** | Right-click web selection → save | `chrome://extensions` → load `extensions/chrome/` |

---

## Tour of the surfaces

### Web UI

| Path | What it does |
|---|---|
| `/dashboard/ui` | Stats, daily review CTA, 7-day activity sparkline → activity timeline, cold-books widget, tag cloud, embedding coverage |
| `/highlights/ui/review` | The daily review queue. `j`/`Space` next, `s`/`f` favorite, `x`/`d`/`#` discard. |
| `/highlights/ui/search` | FTS5 search with `<mark>` snippets, faceted filters, bulk action bar. |
| `/highlights/ui/activity` | Newest-first timeline of every action (favorite/discard/master/...). `g v` from anywhere. |
| `/highlights/ui/ask` | RAG over the library; cites the source highlights. Needs embeddings. |
| `/highlights/ui/h/{id}` | Highlight permalink (OG-rich) — `/quote.png` for the social card. |
| `/highlights/ui/duplicates` | Exact dup groups + bulk-discard. |
| `/highlights/ui/duplicates/semantic` | Cosine-similar pairs with one-click discard. |
| `/library/ui` | Book grid with cover art, filterable by author. |
| `/library/ui/book/{id}` | Book detail with stats panel + LLM summary action. |
| `/library/ui/authors` | Author index sortable by book count or highlight count. |
| `/digest/today` | Stable daily digest (today's pick, today's sample, on-this-day). |
| `/import/ui` | Multi-format import UI. |
| `/import/api-token` | Self-service API token mint. |
| `/settings/ui` | Theme cycle, daily review count, backup, export. |

**Keyboard shortcuts.** Gmail-style `g` then a letter: `g d` dashboard, `g l` library, `g r` review, `g f` favorites, `g x` discarded, `g m` mastered, `g a` ask, `g u` duplicates, `g v` activity, `g i` import, `g s` settings, `g t` API tokens. Press `?` anywhere for the help modal.

### REST API (`/api/v2`)

Auth: `Authorization: Token <raw>` (Readwise convention, **not** `Bearer`). Token minted at `/import/api-token`.

#### Highlights

| Method | Path | What it does |
|---|---|---|
| `GET`    | `/api/v2/auth/` | Token validation (204 on success). |
| `GET`    | `/api/v2/highlights/` | Paginated list. Filters: `book_id`, `favorited`, `discarded`, `mastered`. |
| `POST`   | `/api/v2/highlights/` | Bulk create (Readwise-shaped body). |
| `GET`    | `/api/v2/highlights/search` | FTS5 search with `<mark>` snippets. Filters: `tag`, `include_discarded`, `favorited`, `mastered`. |
| `GET`    | `/api/v2/highlights/random` | One random highlight (`?book_id=` to scope). |
| `GET`    | `/api/v2/highlights/today` | Stable highlight-of-the-day (same all day). |
| `GET`    | `/api/v2/highlights/duplicates` | Exact-text dup groups. |
| `GET`    | `/api/v2/highlights/duplicates/semantic` | Cosine-similar pairs. |
| `GET`    | `/api/v2/highlights/{id}` | Single detail incl. tags + similarity-if-related. |
| `PATCH`  | `/api/v2/highlights/{id}` | Note / favorite / discard / mastered. |
| `POST`   | `/api/v2/highlights/{id}/note/append` | Atomic note append. |
| `GET`    | `/api/v2/highlights/{id}/related` | Top-K semantic similar (needs embeddings). |
| `GET`    | `/api/v2/highlights/{id}/suggest-tags` | Embedding-neighbor tag suggestions. |
| `GET`    | `/api/v2/highlights/{id}/tags` | List tags. |
| `POST`   | `/api/v2/highlights/{id}/tags` | Add tag (idempotent). |
| `DELETE` | `/api/v2/highlights/{id}/tags/{name}` | Remove tag. |

#### Discovery

| Method | Path | What it does |
|---|---|---|
| `GET`  | `/api/v2/books/` | Paginated book list. Filters: `author`, `q` (substring on title or author). |
| `GET`  | `/api/v2/authors` | Distinct authors with counts (`?q=` substring). |
| `GET`  | `/api/v2/tags` | Distinct tags with counts. |
| `GET`  | `/api/v2/stats` | Counts + review-due. |
| `POST` | `/api/v2/tags/{name}/rename` | Global tag rename. |
| `POST` | `/api/v2/tags/{name}/merge` | Merge tag into another. |
| `POST` | `/api/v2/authors/rename` | Rename author across all books. |

#### AI

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v2/ask` | RAG over the library. |
| `POST` | `/api/v2/books/{id}/summarize` | LLM summary of one book. |
| `POST` | `/api/v2/embeddings/backfill` | Run one batch of embeddings (CLI driver). |

#### Logs & ops

| Method | Path | What it does |
|---|---|---|
| `GET`  | `/api/v2/review-log` | Newest-first action log; filter by `action`, `since`. |
| `POST` | `/api/v2/admin/digest/send` | Send the email digest now. |
| `GET`  | `/api/v2/admin/backup` | Stream an atomic SQLite snapshot. |
| `POST` | `/api/v2/kindle` | Kindle JSON ingest endpoint (used by the scraper). |

Full schemas in [`docs/USAGE.md`](docs/USAGE.md). Pagination follows Readwise's `count`/`next`/`previous` envelope.

### `freewise` CLI

```bash
pip install -e cli/                    # or: uv pip install -e cli/
freewise auth login --url https://your-host --token <fw_…>
```

Reads from `~/.config/freewise/config.toml`, falls back to `FREEWISE_URL` / `FREEWISE_TOKEN` env vars.

| Group | Commands |
|---|---|
| **Auth** | `auth login` · `auth status` |
| **Read** | `search` · `recent` · `show` · `random` · `today` · `books` · `book-highlights` · `authors` · `tags` · `stats` · `health` |
| **Write** | `add` · `note` · `favorite` · `unfavorite` · `discard` · `restore` · `master` · `unmaster` · `tag {add,remove,list,rename,merge}` · `author rename` |
| **Discovery** | `duplicates` · `semantic-dupes` · `related` · `suggest-tags` |
| **AI** | `ask` · `summarize-book` · `embed-backfill` |
| **Ops** | `backup` · `digest` · `import` · `export {csv,markdown,atomic,notion}` |

**Filter flags shipped on the read commands** (tri-state):

- `freewise recent --favorited` / `--no-favorited` (also `--discarded`, `--mastered`)
- `freewise search "stoicism" --favorited --tag philosophy`
- `freewise books --author "橘玲"` or `freewise books --q stoic`

`--json` on any command emits structured output for piping.

### `freewise-mcp` MCP server

```bash
pip install -e mcp/                    # or: uv pip install -e mcp/
```

Add to `~/.claude.json`:

```json
{
  "mcpServers": {
    "freewise": {
      "type": "stdio",
      "command": "freewise-mcp",
      "env": {
        "FREEWISE_URL": "https://your-host",
        "FREEWISE_TOKEN": "fw_…"
      }
    }
  }
}
```

Restart Claude Code → 30 tools land:

| Read | Write | Discovery | AI | Ops |
|---|---|---|---|---|
| `freewise_search` | `freewise_set_note` | `freewise_books` | `freewise_ask` | `freewise_stats` |
| `freewise_recent` | `freewise_append_note` | `freewise_book_highlights` | `freewise_summarize_book` | `freewise_health` |
| `freewise_show` | `freewise_favorite` | `freewise_authors` | `freewise_related` | `freewise_backup` |
| `freewise_today` | `freewise_discard` | `freewise_tags` | `freewise_suggest_tags` | |
| `freewise_random` | `freewise_master` | `freewise_tag_list` | `freewise_semantic_dupes` | |
| | `freewise_add` | `freewise_duplicates` | | |
| | `freewise_tag_add` / `_remove` | | | |
| | `freewise_tag_rename` / `_merge` | | | |
| | `freewise_author_rename` | | | |

### Chrome extension

Right-click any web selection → "Save selection to FreeWise" → posts to `/api/v2/highlights/`. MV3, no remote code, token + base URL stored in `chrome.storage.local` only (never `sync` — Google would see the token).

```bash
# 1. chrome://extensions → Developer mode ON → Load unpacked
# 2. Select the folder: extensions/chrome/
# 3. Click the icon → fill in base URL + API token → Save
```

**Automated end-to-end tests** ship with the extension. They boot a fresh FreeWise on `:8064`, mint a temp ApiToken, load the unpacked extension into a real Chromium, and verify popup config + the right-click → POST → search flow:

```bash
bash extensions/chrome/e2e/run.sh
```

---

## Configuration reference

All config is environment variables. `.env` and `.env.qnap` are gitignored — put secrets there.

| Variable | Default | What it does |
|---|---|---|
| `FREEWISE_DB_URL` | `sqlite:///./db/freewise.db` | SQLAlchemy URL. Used by both the app and the CLI's local-DB scripts. |
| `FREEWISE_URL` | `http://localhost:8063` | (CLI/MCP only) base URL of the server. |
| `FREEWISE_TOKEN` | unset | (CLI/MCP only) raw API token. |
| `FREEWISE_OLLAMA_URL` | `http://localhost:11434` | Ollama base URL. |
| `FREEWISE_OLLAMA_EMBED_MODEL` | `nomic-embed-text` | Embedding model. Switch carefully — re-embed required. |
| `FREEWISE_OLLAMA_GENERATE_MODEL` | `llama3.2` | Chat / RAG model. |
| `KINDLE_IMPORTS_DIR` | unset | If set, watcher auto-imports JSON/CSV files dropped here. |
| `KINDLE_SCRAPE_CMD` | unset | Command for the dashboard's "Scrape now" button. Hidden when unset. |
| `KINDLE_SCRAPE_STATE_FILE` | `/tmp/freewise-kindle-scrape.json` | Trigger state for the scrape button. |
| `SMTP_HOST` / `_PORT` / `_USER` / `_PASS` / `_FROM` / `_TO` | unset | Email digest. Digest is silently disabled when any are missing. |

---

## Operations

### Common Docker commands

| Task | Command |
|---|---|
| Start (first time / after update) | `docker compose up -d --build` |
| Start (no rebuild) | `docker compose up -d` |
| Stop (data preserved) | `docker compose down` |
| Stop and **wipe all data** | `docker compose down -v` |
| Follow logs | `docker compose logs -f freewise` |
| Restart only the app | `docker compose restart freewise` |

### Updating

```bash
git pull
docker compose up -d --build
```

Forward-only migrations run automatically on startup. If FTS5 or any column is missing, the app rebuilds it idempotently.

### Backups

The cleanest path is the in-app endpoint (uses `sqlite3.backup()` — atomic, safe under writes):

```bash
freewise backup --to-dir ./backups --retain 7
# → ./backups/freewise-2026-05-04T22-26-00-123456.sqlite
```

Or via raw `curl`:

```bash
curl -H "Authorization: Token $FREEWISE_TOKEN" \
  https://your-host/api/v2/admin/backup -o freewise-$(date +%F).sqlite
```

Volume-tarball still works as a fallback when the app is down:

```bash
docker run --rm \
  -v freewise-db:/data \
  -v "$(pwd)":/backup \
  alpine tar czf /backup/freewise-db-backup.tar.gz -C /data .
```

### Volumes

| Volume | Mount path | Contents |
|---|---|---|
| `freewise-db` | `/srv/freewise/db` | SQLite database (incl. FTS5 index, embeddings) |
| `freewise-covers` | `/srv/freewise/app/static/uploads/covers` | Uploaded book covers |

### Observability

- `GET /healthz` — JSON liveness probe (DB reachable + Ollama if configured)
- `GET /metrics` — Prometheus exposition: `freewise_highlights_total`, `_active`, `_favorited`, `_mastered`, `_books_total`, `_embeddings_count`, `_embedding_coverage`, `freewise_up`
- The `crw-cloudflared` sidecar handles the Cloudflare tunnel for the QNAP deployment used by the maintainer.

---

## Development

```bash
git clone https://github.com/chkk525/FreeWise.git
cd FreeWise

uv sync                                      # creates .venv with all deps
uv run uvicorn app.main:app --reload         # http://localhost:8000

# In another shell, for Tailwind:
npm install
npm run build:css                            # one-shot
npm run watch:css                            # watch mode
```

### Testing

Three independent suites — they can't share a collection because each sets up its own in-process FastAPI app:

| Suite | Tests | Run |
|---|---|---|
| Server | 885 | `uv run pytest tests/` |
| CLI | 50 | `uv run pytest cli/tests/` |
| MCP | 31 | `uv run pytest mcp/tests/` |
| Chrome E2E | 3 | `bash extensions/chrome/e2e/run.sh` |
| **Total** | **969** | `scripts/test_all.sh` (runs all three Python suites sequentially) |

### Project structure

```
app/
├── main.py                       # FastAPI entry + lifespan
├── db.py                         # Engine + forward-only migrations + FTS5 setup
├── models.py                     # SQLModel ORM (Highlight, Book, Tag, ApiToken, ReviewLog, ...)
├── api_v2/                       # Token-gated /api/v2/* endpoints
├── importers/                    # Import pipelines (Kindle JSON, Readwise CSV, ...)
├── middleware/                   # Custom Starlette middleware
├── routers/                      # HTML routes (dashboard, library, highlights, digest, ...)
├── services/                     # cold_books, review_log, search_snippet, embeddings,
│                                 # rag, digest, email, quote_card, kindle_*, book_stats
├── template_filters.py           # Custom Jinja filters
├── templates/                    # Jinja2 HTML
└── static/                       # Compiled CSS, JS, uploaded covers

cli/                              # `freewise` CLI (separate package, own tests, own uv.lock)
mcp/                              # MCP stdio server with 30 tools

extensions/
├── chrome/                       # MV3 Chrome extension
│   └── e2e/                      # Playwright E2E for the extension
└── kindle-importer/              # Legacy MV3 Kindle highlight extractor

scrapers/
└── kindle/                       # Playwright fallback scraper (lives in sibling repo)

shared/                           # Selectors + JSON Schema shared by Python + TS

docs/
├── USAGE.md                      # Reference for every CLI cmd / API endpoint / MCP tool
├── SEMANTIC_SETUP.md             # Ollama install + first-time backfill
├── KINDLE_JSON_SCHEMA.md         # Contract with the Kindle scraper
└── KINDLE_BROWSER_EXTENSION.md   # MV3 extension architecture, install, error matrix

tests/                            # Server pytest suite
CHANGELOG.md                      # Theme-grouped changelog
Dockerfile                        # Multi-stage Node → Python production image
docker-compose.yml                # Single-service deployment
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| **Search returns no results for a known term** | FTS5 index stale or missing. | Restart — the lifespan rebuilds it. Or hit `/healthz` to confirm the column counts. |
| **`/api/v2/highlights/?favorited=true` returns everything** | You're on a pre-PR-#9 build. | `git pull && docker compose up -d --build`. |
| **`freewise auth login` reports 401** | Token has whitespace or you used `Bearer` instead of `Token`. | Re-mint at `/import/api-token`. The CLI strips whitespace; raw curl needs `Authorization: Token <raw>`. |
| **`/highlights/ui/ask` says "no embeddings"** | Backfill never ran. | `freewise embed-backfill --batch-size 64` — idempotent, resumable. |
| **Chrome extension "FreeWise: HTTP 401"** | Wrong base URL or token. | Click the extension icon → Test connection. |
| **Email digest never arrives but `freewise digest` succeeds dry-run** | One of the SMTP env vars is missing. | `docker compose exec freewise env \| grep SMTP` to confirm. Digest fails closed (silent) when any var is unset. |
| **`docker compose down -v` deleted my highlights** | The `-v` flag wipes named volumes by design. | Restore from `freewise backup` snapshot. **Always backup before `down -v`.** |
| **Kindle scraper found 0 books** | Amazon changed selectors or your session cookie expired. | Re-auth in the [`freewise-qnap-kindle`](https://github.com/chkk525/freewise-qnap-kindle) repo's setup flow. |
| **Author X appears under multiple slightly-different names** | Full-width / half-width spaces or trailing typos in the source data. | `freewise author rename "old" "new"` consolidates into one canonical entry. |

For anything else, check `docker compose logs -f freewise` and grep for `ERROR`. Most issues are visible there.

---

## Roadmap

**Confirmed wishlist** (autonomous-safe — implementable without UX redesign):

- [ ] PWA full offline mode (Service Worker + IndexedDB cache).
- [ ] Differential Kindle scrape (only changed books since last run).
- [ ] PDF / EPUB attachment view inline on the book detail page.
- [ ] Notion bidirectional sync for "currently reading" state.

**Big-ticket items needing user decision**:

- A3 — Email digest body redesign (HTML mockup pending).
- A7 — Multi-device read state (would break the "single user" invariant).

See [`CHANGELOG.md`](CHANGELOG.md) for what already shipped and roughly when.

---

## Contributing

This is a single-user fork — open issues for bugs, but **PRs are not merged upstream from here**. The original [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise) is the place for upstream work.

If you want to fork the fork: go ahead, it's CC0. Conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`) preferred. Tests for new features expected (the suite is fast — 969 tests in ~15s combined).

---

## Acknowledgements

Built on [`wardeiling/FreeWise`](https://github.com/wardeiling/FreeWise) — the CRUD/import/review baseline is unchanged. The fork adds search, AI/RAG, multi-surface (CLI + MCP + extension), Kindle scraping, and operations layers.

Inspired by [Readwise](https://readwise.io) — gratitude for proving the daily-review loop works. This is the self-hosted answer for people who wanted that loop without renting it.

---

## License

[CC0](LICENSE) — same as upstream. Take it, fork it, port it, sell it.
