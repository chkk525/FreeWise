# FreeWise CLI Plan

## Context

User wants `freewise` CLI usable from Claude Code (Bash tool). Current state:

- `feat/kindle-importer` branch ships HTML/HTMX routes only (no JSON API yet).
- `feat/readwise-api-v2` branch on main repo added the `ApiToken` model but no `/api/v2/*` endpoints are implemented yet.
- `/export/csv` is the only existing JSON-ish data source.

Building a CLI today against HTML scraping would be fragile, so this plan ships a **thin internal JSON API** alongside the CLI in the same round.

## Goals

1. `freewise <subcommand>` works from any shell (incl. Claude Code Bash).
2. Auth uses the existing `ApiToken` model (Bearer token in header).
3. Output is line-oriented + JSON-friendly so it pipes well.
4. CLI surface mirrors what an MCP server would expose later — same verbs, same arg shapes.
5. Zero new heavy dependencies. `httpx` is already in deps; if not, use stdlib `urllib`.

Non-goals this round:
- Full Readwise API v2 compatibility (separate feat branch already owns that).
- MCP server (next round; this round's CLI is shaped to wrap cleanly).
- Local-only mode that opens the SQLite directly without a running server.

## Architecture

```
        ┌───────────┐    HTTP+Bearer    ┌────────────────────┐
        │ freewise  │ ─────────────────▶│ FreeWise FastAPI   │
        │  CLI      │                   │  /api/v1/*         │
        └───────────┘                   │  (NEW — thin)      │
              ▲                         │                    │
              │ stdout (text or JSON)   │  /export/csv       │
              ▼                         │  /highlights/ui/*  │
        Claude Code (Bash)              └────────────────────┘
```

### New `/api/v1/*` JSON endpoints (minimum viable)

| Verb | Path | Purpose |
|------|------|---------|
| GET  | `/api/v1/highlights/search?q=&limit=` | Full-text search → JSON list |
| GET  | `/api/v1/highlights/recent?limit=&since=` | Recent active highlights |
| GET  | `/api/v1/highlights/{id}` | Single highlight detail |
| GET  | `/api/v1/review/today` | Today's review queue |
| GET  | `/api/v1/stats` | Counts, streak, last_import |
| POST | `/api/v1/highlights` | Create highlight (manual capture) |
| POST | `/api/v1/highlights/{id}/note` | Update note |
| POST | `/api/v1/highlights/{id}/favorite` | Toggle favorite |

All require `Authorization: Bearer <token>` validated against `ApiToken.token` (the model already exists).

### CLI subcommands (Phase 1)

```
freewise auth login --token <T>           # save token to ~/.config/freewise/config.toml
freewise auth status                      # show server URL + masked token

freewise search <query> [--limit 20] [--json]
freewise recent [--limit 10] [--since 7d] [--json]
freewise show <id> [--json]
freewise review [--json]                  # today's queue
freewise stats [--json]

freewise add --book "Title" --author "..." --text "..." [--note "..."]
freewise note <id> "<text>"               # set/clear note
freewise favorite <id>                    # toggle

freewise export csv [-o file]             # streams /export/csv
freewise export markdown [-o file]        # streams Markdown ZIP (next round, U24)
```

### Packaging

- New top-level `cli/` directory (sibling of `app/`) with its own `pyproject.toml` so the CLI is `pip install`-able **without** the FastAPI server (the user might want CLI-only on a laptop pointing at a remote QNAP).
- Script entry: `freewise = "freewise_cli.main:main"`.
- Single dependency: `httpx` (or stdlib `urllib`).
- Config file at `${XDG_CONFIG_HOME:-~/.config}/freewise/config.toml`.
- Env-var override: `FREEWISE_URL`, `FREEWISE_TOKEN`.

## Phasing

### This round (autonomous)
1. Add `app/routers/api_v1.py` with the 8 endpoints above. Bearer-token auth via dependency that reads `ApiToken`. Tests for each.
2. Add `cli/freewise_cli/main.py` argparse skeleton + auth + 5 read commands (search, recent, show, review, stats). Tests via TestClient.
3. Add `cli/README.md` with install + usage examples for Claude Code.
4. Wire into deploy (no server changes needed — endpoints just light up).

### Next round
5. CLI write commands (add, note, favorite).
6. CLI export wrappers.
7. Markdown export endpoint (U24 deferred from this round).

### Round after
8. MCP server wrapping the CLI surface for native Claude Code integration.

## Open questions to confirm before coding

1. **API version path**: `/api/v1/*` (this app's own) or `/api/v2/*` (Readwise-compat alias the main-repo branch is building)? **My pick: `/api/v1/*` for now** — it's our own surface, not pretending to be Readwise. The Readwise-compat layer can be a separate alias later.
2. **CLI package location**: `cli/` sibling of `app/` (proposed) or `app/cli/` submodule of the server?
3. **Auth**: pure Bearer token, or also accept the `freewise_session` cookie that the UI uses, for "I'm on the same machine, I'm already logged in" convenience?
4. **Output format default**: human-readable text (Phase 1 plan) or JSON-by-default? `--json` flag is included either way.

## Risk / things I'd worry about

- **`ApiToken.token` is stored raw** (the model comment notes it as a v1 known issue). Bearer-auth dependency must use `hmac.compare_digest` against the raw value. Hashing to come later — out of scope for this round.
- The `/api/v1/highlights/recent?since=7d` parser needs to handle the same time-range input the user types in `freewise recent --since 7d`. Standard humanize parsing or just accept ISO + suffix shorthand.
- Single-user app today; the `user_id` on tokens means the API is technically multi-user but the UI ignores user scoping. CLI follows UI behavior (treats everything as user 1) until auth lands.
