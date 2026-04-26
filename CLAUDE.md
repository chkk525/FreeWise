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

## Tests

This fork has three independent pytest suites that can't share a collection
(each sets up its own in-process FastAPI app):

```bash
scripts/test_all.sh             # runs all three sequentially
uv run pytest tests/            # main app (~423 tests)
uv run pytest cli/tests/        # CLI (~20 tests)
uv run pytest mcp/tests/        # MCP server (~13 tests)
```

## Tools shipped on this fork

### `freewise` CLI (in `cli/`)

```bash
uv pip install -e cli/        # installs the `freewise` console script
freewise --help               # see all subcommands
freewise auth login --token fw_xxx
freewise search "stoicism"
freewise stats
freewise export markdown -o vault.zip
```

Reads config from `~/.config/freewise/config.toml` and env vars `FREEWISE_URL`/`FREEWISE_TOKEN`. Full docs: `cli/README.md`.

### `freewise-mcp` MCP server (in `mcp/`)

```bash
uv pip install -e mcp/        # installs the `freewise-mcp` console script
```

Then add to `~/.claude.json`:

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

Exposes 9 tools to Claude Code: `freewise_search`, `_recent`, `_show`, `_stats`, `_books`, `_set_note`, `_favorite`, `_discard`, `_add`. Full docs: `mcp/README.md`.

## API surface added on this fork

Beyond the upstream HTML/HTMX UI:

| Method | Path | Purpose |
|---|---|---|
| GET   | `/api/v2/auth/`              | Token validation |
| POST  | `/api/v2/highlights/`        | Bulk create (Readwise-shaped) |
| GET   | `/api/v2/highlights/`        | Paginated list |
| GET   | `/api/v2/highlights/search`  | LIKE search (text+note) — fork extension |
| GET   | `/api/v2/highlights/{id}`    | Single detail (incl. tags) — fork extension |
| PATCH | `/api/v2/highlights/{id}`    | Note/favorite/discard/mastered — fork extension |
| GET   | `/api/v2/highlights/{id}/tags`        | List highlight tags — fork extension |
| POST  | `/api/v2/highlights/{id}/tags`        | Add tag (idempotent) — fork extension |
| DELETE| `/api/v2/highlights/{id}/tags/{name}` | Remove tag (idempotent) — fork extension |
| GET   | `/api/v2/books/`             | Paginated book list |
| GET   | `/api/v2/stats`              | Counts + review-due — fork extension |
| GET   | `/export/csv`                | Readwise-compatible CSV |
| GET   | `/export/markdown.zip`       | Obsidian/Logseq vault ZIP — fork addition |
| GET   | `/export/atomic-notes.zip`   | One .md per highlight (Zettelkasten atoms) — fork addition |
| GET   | `/export/notion.zip`         | Notion-flavored Markdown vault ZIP — fork addition |
| GET   | `/export/book/{id}.md`       | Single book as Markdown (?flavor=obsidian\|notion) — fork addition |
| POST  | `/settings/backup.db`        | SQLite VACUUM INTO snapshot |
| POST  | `/settings/theme/toggle`     | Cycle light → dark → auto |

Auth on `/api/v2/*` uses `Authorization: Token <raw>` (Readwise convention, **not** `Bearer`).

## In-flight ideas (not started)

See `docs/CLI_PLAN.md` for the latest roadmap. Big-ticket items not yet
agreed:

- **C2** semantic similarity (related-highlight surfacing) — needs ML dep decision (sentence-transformers vs fastembed vs Ollama)
- **A1** highlight-level tag UI — model exists but no UI yet
- **B4** bulk operations on lists
- **B1** FTS5 migration for search
