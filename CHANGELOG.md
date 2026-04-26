# Changelog — chkk525 fork

Tracks additions on top of upstream `wardeiling/FreeWise`. Grouped by
theme, not chronology — rough commit ID in parentheses.

> Format: this file documents the **fork**'s additions. For upstream
> changes see git history. For day-to-day usage see `docs/USAGE.md`.

---

## Search & discovery

- **FTS5 trigram index** for substring search (U91). Works for any
  language including Japanese / Chinese without MeCab. Migration runs
  on first start with auto-backfill; LIKE fallback if the linked SQLite
  lacks FTS5. (`0d2c21a`)
- **Search facets** — `?favorited_only=true`, `?has_note=true`, `?tag=X`
  on `/highlights/ui/search`. Filter-only browsing valid (no `q`
  required). (U87, `067fc98`)
- **Author index** at `/library/ui/authors` with sort tabs
  (highlights / books / name / recent). Per-author summary card
  from U74 already shows on `?author=X` filter. (U85, `4a5a968`)
- **Per-tag detail page** at `/highlights/ui/tag/{name}`. (U73, `a29eff2`)
- **On-this-day** dashboard widget — past-year highlights for today's
  MM-DD. (U80, `9aa2e88`)
- **Daily-pick** widget — deterministic highlight of the day; same
  pick all day, salt-overridable. (U68/U69, `b4873e1` `30a3ad2`)

## AI / RAG (Ollama-backed)

- **Embedding substrate** + backfill + cosine retrieval. (U48-U50,
  `0318b6b` `df27ca3` `f14f37d`)
- **`/ask` RAG endpoint** + UI page + dashboard widget — answers
  questions over the library with citation links. (U52/U53, `9033363`
  `952665d`)
- **Per-book summarize** — LLM summary using only that book's
  highlights. (U55/U56, `f5b90be` `1cab7f3`)
- **Tag suggestions** — embedding-neighbor-based suggested tags for one
  highlight. (U72, `7fa71bc`)
- **Semantic near-duplicate detection** — heap-bounded chunked matmul
  over up to 25k×768 vectors. UI at `/highlights/ui/duplicates/semantic`,
  process-local mutex against concurrent triggers. (U71/U76,
  `2fd77a8` `5f4820d`)

## Curation & cleanup

- **Exact duplicate finder** — leading-character grouping with one-click
  bulk cleanup. (U59/U60, `a36390e` `c462868`)
- **Library-health card** on dashboard — duplicate-group count + tagging
  coverage % with backfill CTAs. Defer-loaded so it doesn't block the
  main page. (U78/U84/U86, `58f088a` `0fdef5b` `07df4b3`)
- **Tag rename / merge / autocomplete** — rename across entire library,
  merge two tags into one, native `<datalist>` suggestions on bulk-tag
  input. (U54/U93, `aba0a8a` `e393269`)
- **Author rename** — single API/CLI/MCP call updates every book.
  (U54, `aba0a8a`)
- **Append-to-note** — atomic concat with 8191-char cap. (U64, `f2a85ac`)
- **Quick capture** — dashboard textarea for one-click highlight save.
  (U61, `3d90021`)
- **Copy-as-quote** button on every highlight row — formats
  `"text"\n— Author, Title` to clipboard. (U82, `0a1add5`)
- **Notes formatting** — preserve line breaks + auto-link bare http(s)
  URLs (XSS-safe; javascript:/data: schemes rejected). (U81, `36a0220`)
- **Trailing-punctuation strip** in autolinks so "see https://x.com."
  doesn't link the period. (U83, `55d238b`)

## Open Graph / sharing

- **Rich link previews** on `/highlights/ui/h/{id}` — og:type/title/
  description + Twitter Card meta. Slack / iMessage / Twitter all
  expand. (U93, `e393269`)
- **Permalink page** with HTMX-deferred related highlights.
  (`c12a89f` baseline + later polish)

## Import / export

- **CLI import** — `freewise import path` auto-detects Readwise CSV /
  Kindle JSON / Meebook HTML. (U70, `e723e54`)
- **Kindle notebook auto-import** — watcher + scan-now manual trigger
  + dedup-by-ASIN + dashboard status card. (early Kindle batch)
- **Filtered CSV / Markdown export** — `tag`, `book_id`, `author`,
  `favorited_only`, `active_only` all conjunctive. (U88 + U93,
  `1d00fc3` `e393269`)

## Operations

- **`/healthz`** — counts + Ollama reachability. (U58, `d2bb79b`)
- **`/metrics`** — Prometheus text format, 7 gauges, no auth.
  (U89, `d8d90c1`)
- **`/api/v2/admin/backup`** — atomic SQLite snapshot via
  `sqlite3.backup()`. Token-gated, dedicated 3 req/IP/min rate
  bucket. (U77, `affcba0`)
- **CLI backup rotation** — `freewise backup --to-dir DIR --retain N`
  for cron, ms-precision timestamps to avoid collisions. (U90/U92,
  `638f123` `6d209d5`)
- **Per-IP rate limiter** + security headers. (early H8/H9 batch,
  `0955a77`)
- **Hashed API tokens** + CSRF + revocation. (`494ac7d`)

## Multi-surface (CLI + MCP)

- **`freewise` CLI** — 36+ subcommands across discovery, curation,
  inventory, ops. Configured once via `freewise auth login`.
- **MCP server** — 30 stdio tools so a Claude Code session has
  first-class read/write access to the library.

## UI

- **Dashboard** — defer-loaded library-health + on-this-day partials
  so the synchronous handler stays cheap on a 25k-row library.
  (U86, `07df4b3`)
- **Embedding-coverage indicator** + tag cloud. (U50)
- **Mobile-friendly review shortcuts** — visible `<kbd>` labels under
  every action button (mobile users can't hover to see `title=`). (`ef94634`)
- **Author summary card** on filtered library view. (U74, `abe7ff7`)
- **Tagging-coverage card** with bulk-tag CTA + `freewise suggest-tags`
  hint. (U84, `0fdef5b`)
- **Random highlight** widget. (`0c8...` baseline)

## Engineering

- **Forward-only schema migrations** keep existing DBs upgrading without
  alembic.
- **Defer-load HTMX pattern** for dashboard widgets — main page returns
  instantly even when individual widgets do full-table scans.
- **`make_templates()` helper** centralizes Jinja2Templates +
  filter registration in one call site (U94, `f2044dd`).
- **Code reviews** at U57, U67, U75, U79, U83, U92 — every batch
  inspected for CRITICAL/HIGH issues before the next batch starts.

## Documentation

- **`docs/USAGE.md`** — single-page reference for CLI / API / web UI /
  MCP surfaces (U95, `3235323`)
- **`docs/SEMANTIC_SETUP.md`** — Ollama install + first-time backfill
  instructions.
- **`docs/KINDLE_JSON_SCHEMA.md`** — contract for the Kindle scraper
  feed.

---

## Test coverage

Server: 727 · CLI: 42 · MCP: 31 · **Total: 800 passing.**

Coverage spans CRUD, RAG mocked-Ollama, FTS5 trigger sync, HTMX
defer-load wiring, XSS regression on autolinks, FTS5 query escaping,
backup rate-limit firing, and more.
