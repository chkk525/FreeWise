# CLAUDE.md — fork-specific notes for Claude Code

This file documents what `chkk525/FreeWise` adds on top of the upstream
`wardeiling/FreeWise` so future Claude Code sessions can pick up where the
last left off.

> **Important policy**: Never open a PR to the upstream `wardeiling/FreeWise`
> repo. All work stays on the `chkk525` fork.

## Repos / worktrees

| Path | Branch | Purpose |
|---|---|---|
| `~/Development/freewise-kindle/` | `feat/kindle-importer` | Active development (this fork) |
| `~/Development/freewise/` | `feat/readwise-api-v2` | Sister branch — Readwise API v2 work in progress |
| `~/Development/freewise-qnap-deploy/` | (deploy scripts) | Cloudflare-tunnel + cron + deploy_qnap.sh for the QNAP host |

## Deploy

```bash
LOCAL_SRC=~/Development/freewise-kindle bash ~/Development/freewise-qnap-deploy/tools/deploy_qnap.sh
```

Lives at `http://192.168.0.171:8063` on the LAN, `https://freewise.chikaki.com` behind Cloudflare Access.

> **Gotcha**: production pip deps come from `~/Development/freewise-qnap-deploy/requirements.qnap.txt`,
> NOT from the kindle-fork's `requirements.txt`. Adding a new Python dep means editing **both** files.

## Tests

This fork has three independent pytest suites that can't share a collection
(each sets up its own in-process FastAPI app):

```bash
scripts/test_all.sh             # runs all three sequentially
uv run pytest tests/            # main app (~542 tests)
uv run pytest cli/tests/        # CLI (~29 tests)
uv run pytest mcp/tests/        # MCP server (~24 tests)
```

Total: ~595 tests across the stack.

## Tools shipped on this fork

### `freewise` CLI (in `cli/`)

```bash
uv pip install -e cli/        # installs the `freewise` console script
freewise --help               # see all subcommands
freewise auth login --token fw_xxx
freewise stats
freewise search "stoicism" [--tag philosophy] [--limit 20]
freewise recent [--limit 10]
freewise show <id>
freewise random [--book-id N]
freewise related <id>                       # semantic similarity (needs Ollama)
freewise books | authors | tags             # discovery surface
freewise book-highlights <id>
freewise tag {add|remove|list} <id> [tag]
freewise note <id> "..."
freewise favorite <id> | unfavorite <id>
freewise discard <id> | restore <id>
freewise master <id> | unmaster <id>
freewise add --text "..." --book "..." --author "..."
freewise export csv|markdown|atomic|notion [-o file] [--book-id N]
freewise embed-backfill [--batch-size N] [--max M] [--model X]
```

Reads config from `~/.config/freewise/config.toml` and env vars
`FREEWISE_URL`/`FREEWISE_TOKEN`. Full docs: `cli/README.md`.

### `freewise-mcp` MCP server (in `mcp/`)

```bash
uv pip install -e mcp/        # installs the `freewise-mcp` console script
```

Add to `~/.claude.json`:

```jsonc
{
  "mcpServers": {
    "freewise": {
      "type": "stdio", "command": "freewise-mcp",
      "env": {
        "FREEWISE_URL": "https://freewise.chikaki.com",
        "FREEWISE_TOKEN": "fw_xxx"
      }
    }
  }
}
```

**18 tools** exposed to Claude Code:

| Read tools | Write tools | Discovery / pivots |
|---|---|---|
| `freewise_search` | `freewise_set_note` | `freewise_books` |
| `freewise_recent` | `freewise_favorite` | `freewise_book_highlights` |
| `freewise_show` | `freewise_discard` | `freewise_authors` |
| `freewise_random` | `freewise_master` | `freewise_tags` |
| `freewise_related` (semantic) | `freewise_add` | `freewise_tag_list` |
| `freewise_stats` | `freewise_tag_add` | `freewise_tag_remove` |

Full docs: `mcp/README.md`.

## API surface added on this fork

Beyond the upstream HTML/HTMX UI:

### Auth + bulk

| Method | Path | Purpose |
|---|---|---|
| GET   | `/api/v2/auth/` | Token validation |
| POST  | `/api/v2/highlights/` | Bulk create (Readwise-shaped) |

### Highlights

| Method | Path | Purpose |
|---|---|---|
| GET   | `/api/v2/highlights/` | Paginated list (`?book_id=` to filter) |
| GET   | `/api/v2/highlights/search` | LIKE search (`?q=&tag=&include_discarded=`) |
| GET   | `/api/v2/highlights/random` | One random highlight (`?book_id=&include_*=`) |
| GET   | `/api/v2/highlights/{id}` | Single detail (incl. tags + similarity if related) |
| PATCH | `/api/v2/highlights/{id}` | Note/favorite/discard/mastered |
| GET   | `/api/v2/highlights/{id}/related` | Top-K semantic similar (needs embeddings) |
| GET   | `/api/v2/highlights/{id}/tags` | List highlight tags |
| POST  | `/api/v2/highlights/{id}/tags` | Add tag (idempotent) |
| DELETE| `/api/v2/highlights/{id}/tags/{name}` | Remove tag (idempotent) |

### Discovery

| Method | Path | Purpose |
|---|---|---|
| GET   | `/api/v2/books/` | Paginated book list |
| GET   | `/api/v2/authors` | Distinct authors with counts (`?q=` substring) |
| GET   | `/api/v2/tags` | Distinct tags with counts (`?q=` substring) |
| GET   | `/api/v2/stats` | Counts + review-due |

### Embeddings (C2)

| Method | Path | Purpose |
|---|---|---|
| POST  | `/api/v2/embeddings/backfill` | Run one batch of embeddings (CLI driver) |

### Exports + ops

| Method | Path | Purpose |
|---|---|---|
| GET   | `/export/csv` | Readwise-compatible CSV |
| GET   | `/export/books.csv` | Book inventory CSV |
| GET   | `/export/markdown.zip` | Obsidian/Logseq vault ZIP |
| GET   | `/export/atomic-notes.zip` | One .md per highlight (Zettelkasten atoms) |
| GET   | `/export/notion.zip` | Notion-flavored Markdown vault ZIP |
| GET   | `/export/book/{id}.md` | Single book as Markdown (`?flavor=obsidian\|notion`) |
| POST  | `/settings/backup.db` | SQLite VACUUM INTO snapshot |
| POST  | `/settings/theme/toggle` | Cycle light → dark → auto |

### HTML / HTMX surfaces (fork additions)

| Method | Path | Purpose |
|---|---|---|
| GET | `/highlights/ui/h/{id}` | Permalink page for one highlight |
| GET | `/highlights/ui/h/{id}/related` | HTMX partial: related highlights section |
| GET | `/highlights/ui/random` | HTMX partial: dashboard random card |
| GET | `/highlights/ui/mastered` | List of mastered highlights |
| GET | `/highlights/ui/search?q=&tag=` | Full-text search page |
| POST | `/highlights/{id}/master` | Toggle mastery (HTMX) |
| POST | `/highlights/{id}/tags/add` | Add tag chip (HTMX) |
| POST | `/highlights/{id}/tags/remove` | Remove tag chip (HTMX) |
| POST | `/highlights/bulk` | Bulk action (favorite/discard/master/tag/...) |
| GET | `/library/ui?author=X` | Library filtered by author |

Auth on `/api/v2/*` uses `Authorization: Token <raw>` (Readwise convention, **not** `Bearer`).

## Semantic similarity (C2) — Ollama setup

The `related` endpoint, MCP tool, and dashboard coverage indicator all
read from the `embedding` table populated by `freewise embed-backfill`.

```bash
# 1. Run Ollama somewhere reachable from the QNAP container
ollama pull nomic-embed-text     # default model

# 2. Tell FreeWise about it
export FREEWISE_OLLAMA_URL=http://<your-host>:11434
export FREEWISE_OLLAMA_EMBED_MODEL=nomic-embed-text  # or any embedding model

# 3. Run backfill (loops in batches; idempotent)
freewise embed-backfill --batch-size 64
```

Without Ollama, the rest of the app is unaffected — related-highlights
sections show a "not yet embedded" hint and the dashboard shows 0%
coverage. See `docs/SEMANTIC_SETUP.md` for full notes.

## Roadmap items still open

Big-ticket items needing user decision:

- **A3** Email digest — needs SMTP credentials
- **A7** PWA offline review — multi-hour Service Worker investigation
- **B1** FTS5 search migration — Japanese tokenizer choice (default `unicode61`
  doesn't segment CJK)

Smaller autonomous-safe ideas:
- Tag rename / merge utilities
- Author rename utility (typo fix)
- Reading log endpoint (which highlights were viewed when)
- Daily digest static page (`/digest/today`)
- Per-book stats panel on book detail page
