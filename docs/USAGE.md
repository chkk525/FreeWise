# FreeWise — Usage Reference (chkk525 fork)

Single-page reference for everything the fork adds on top of upstream
`wardeiling/FreeWise`. For the upstream feature list see `README.md`.

> Most surfaces are token-gated under `/api/v2/*`. Get a token from
> `/import/api-token` (web UI) or `freewise auth login`. HTML routes
> under `/highlights/ui/*`, `/library/ui/*`, `/dashboard/ui` rely on
> a single-user-mode hardcoded `user_id=1`; protect them with
> Cloudflare Access (or equivalent) for any non-LAN deployment.

---

## CLI — `freewise`

Install once: `pip install -e cli/` from the repo root.
Configure: `freewise auth login --url http://… --token …`.

### Discovery & reading

| Command | What it does |
|---|---|
| `freewise search "query"` | Full-text search (FTS5 trigram for ≥3 chars; LIKE fallback) |
| `freewise recent [--limit N]` | Newest highlights |
| `freewise show ID` | Detail view of one highlight |
| `freewise random [--book ID]` | Surprise-me pick |
| `freewise today [--salt S]` | Deterministic highlight-of-the-day |
| `freewise duplicates` | Exact-prefix duplicate groups |
| `freewise semantic-dupes [--threshold 0.92]` | Embedding-based near-duplicates |
| `freewise related ID` | Top-K semantically similar highlights |
| `freewise ask "question"` | RAG over your library (needs Ollama) |
| `freewise summarize-book ID` | LLM summary of one book |

### Curation

| Command | What it does |
|---|---|
| `freewise add --text "…" --book "…" --author "…"` | Manual capture |
| `freewise favorite ID` / `unfavorite ID` | Toggle favorited flag |
| `freewise master ID` / `unmaster ID` | Toggle mastered flag (excludes from review) |
| `freewise discard ID` / `restore ID` | Toggle discarded flag |
| `freewise note ID --text "…" [--append]` | Set or append-to note |
| `freewise tag list ID` / `add ID T` / `remove ID T` | Per-highlight tag CRUD |
| `freewise tag rename OLD NEW` | Global rename |
| `freewise tag merge SRC --into DST` | Merge (links combine, source deleted) |
| `freewise author rename OLD NEW` | Rename across every book |
| `freewise suggest-tags ID` | Embedding-based tag suggestions |

### Inventory & stats

| Command | What it does |
|---|---|
| `freewise tags` | All highlight-level tags with counts |
| `freewise authors` | All authors with book + highlight counts |
| `freewise books` | Books with at least one highlight |
| `freewise book-highlights ID` | All highlights from one book |
| `freewise stats` | Aggregate counts + review-due summary |
| `freewise health` | Liveness probe (counts + Ollama reachability) |

### Import / export

| Command | What it does |
|---|---|
| `freewise import path.csv` | Auto-detects Readwise CSV, Kindle JSON, Meebook HTML |
| `freewise export csv [--out PATH]` | Full library CSV |
| `freewise export markdown [--out PATH]` | Per-book .md ZIP (Obsidian-friendly) |
| `freewise export atomic-notes [--out PATH]` | One .md per highlight |
| `freewise embed-backfill` | Populate embeddings for active highlights |

### Backup

| Command | What it does |
|---|---|
| `freewise backup [--out PATH]` | One-off SQLite snapshot |
| `freewise backup --to-dir DIR --retain N` | Cron-friendly: `0 3 * * * freewise backup --to-dir /backups --retain 7` |

### Global flags

`--json`, `--url`, `--token` work on every subcommand.

---

## HTTP API — `/api/v2/*` (token-gated)

Auth header: `Authorization: Token <raw>`.

### Highlights

| Endpoint | Notes |
|---|---|
| `GET /auth/` | Token validation ping (204 / 401) |
| `POST /highlights/` | Readwise-shaped create payload |
| `GET /highlights/` | Paginated list |
| `GET /highlights/{id}` | Single detail |
| `PATCH /highlights/{id}` | Partial update (note, flags, …) |
| `GET /highlights/search?q=…` | FTS5-backed substring search; supports `tag`, `include_discarded` |
| `GET /highlights/today[?salt=…]` | Deterministic daily pick |
| `GET /highlights/random[?book_id=…]` | Random pick |
| `GET /highlights/duplicates` | Exact-prefix duplicate groups |
| `GET /highlights/duplicates/semantic?threshold=0.92` | Heap-bounded matmul over embeddings |
| `GET /highlights/{id}/related?limit=10` | Top-K cosine similarity |
| `GET /highlights/{id}/suggest-tags` | Suggest tags from neighbors |
| `POST /highlights/{id}/note/append` | Append to note (8191-char cap) |
| `POST /ask` | RAG over the library |
| `POST /books/{id}/summarize` | Per-book LLM summary |
| `POST /embeddings/backfill` | Embed N more highlights |

### Tags & authors

| Endpoint | Notes |
|---|---|
| `GET /tags` | All tag names with counts |
| `GET /authors` | All authors with counts |
| `GET /highlights/{id}/tags` | Per-highlight tag list |
| `POST /highlights/{id}/tags` | Attach tag |
| `DELETE /highlights/{id}/tags` | Remove tag |
| `POST /tags/{name}/rename` | Global tag rename |
| `POST /tags/{name}/merge` | Merge tags |
| `POST /authors/rename` | Rename author across books |

### Stats & ops

| Endpoint | Auth | Notes |
|---|---|---|
| `GET /stats` | Token | Aggregate counts |
| `GET /admin/backup` | Token | Atomic SQLite snapshot. 3 req/IP/min cap. |
| `GET /export/csv` | None* | Full library CSV. Filter params: `tag`, `book_id`, `author`, `favorited_only`, `active_only` |
| `GET /export/markdown.zip` | None* | Same filter params as `/export/csv`. Per-book `.md` files. |
| `GET /healthz` | None | Counts + Ollama reachability |
| `GET /metrics` | None | Prometheus exposition (7 gauges) |

\* Unprotected because they're meant to be reachable by external scrapers (cron, Grafana). Single-user mode + Cloudflare Access is the gate.

---

## Web UI — `/dashboard`, `/library`, `/highlights/ui/*`

Notable additions over upstream:

| Page | Notes |
|---|---|
| `/dashboard/ui` | Defer-loaded library-health card (dups + tagging coverage), on-this-day past-year highlights, tag cloud, embedding-coverage indicator, daily-pick widget. |
| `/highlights/ui/today` | Today's highlight (HTMX partial used by dashboard) |
| `/highlights/ui/random` | Random pick |
| `/highlights/ui/ask` | RAG question form |
| `/highlights/ui/quick-capture` | Inline highlight create |
| `/highlights/ui/duplicates` | Exact-prefix dup cleanup |
| `/highlights/ui/duplicates/semantic` | Embedding-based dup pairs (process-local mutex against concurrent matmul) |
| `/highlights/ui/h/{id}` | Permalink page with OG / Twitter Card meta tags for rich link previews |
| `/highlights/ui/tag/{name}` | Per-tag detail listing |
| `/highlights/ui/mastered` | Mastered-only listing |
| `/highlights/ui/search?q=…&favorited_only=true&has_note=true&tag=…` | Faceted search |
| `/library/ui?author=…` | Per-author summary card (engagement chips) + filtered books |
| `/library/ui/authors` | Browseable author index with sort tabs |

The bulk-action bar (visible whenever you tick selection checkboxes) supports favorite / unfavorite / discard / restore / master / tag / untag with native `<datalist>` tag suggestions.

---

## MCP — 30 tools via stdio

Stdio server: `python -m freewise_mcp.server`. Configure once in your Claude Code settings; restart and the `freewise_*` tools appear.

Tool families:

- **Discovery:** `freewise_search`, `freewise_recent`, `freewise_show`, `freewise_random`, `freewise_today`
- **AI:** `freewise_ask`, `freewise_summarize_book`, `freewise_suggest_tags`, `freewise_related`, `freewise_semantic_dupes`
- **Curation:** `freewise_set_note`, `freewise_append_note`, `freewise_favorite`, `freewise_discard`, `freewise_master`, `freewise_add`
- **Tags:** `freewise_tag_list`, `freewise_tag_add`, `freewise_tag_remove`, `freewise_tag_rename`, `freewise_tag_merge`, `freewise_author_rename`
- **Inventory:** `freewise_tags`, `freewise_authors`, `freewise_books`, `freewise_book_highlights`, `freewise_stats`
- **Ops:** `freewise_health`, `freewise_backup`, `freewise_duplicates`

---

## Operational notes

- **FTS5:** populated on first start. Rebuilds if `highlight_fts` row count diverges from `highlight`. Falls back to LIKE on SQLite builds without FTS5.
- **Ollama:** required for `/ask`, `/related`, `/suggest-tags`, `/duplicates/semantic`, summarize. See `docs/SEMANTIC_SETUP.md`.
- **Rate limits:** 60 req/IP/min on `/api/v2/*`; backup is further capped at 3 req/IP/min.
- **Backups:** the `/api/v2/admin/backup` response is a full credential dump (includes api tokens). Treat the file like a `.env`.
- **Single-user mode:** every HTML route hardcodes `user_id=1`. Multi-user requires a code change.
