# `freewise` CLI

Command-line client for [FreeWise](../). Designed for shell + **Claude Code** use.

## Install

```bash
# From the freewise-kindle checkout:
uv pip install -e cli/

# Or just point Python at the package:
PYTHONPATH=cli python -m freewise_cli ...
```

## Auth

The CLI talks to the FreeWise server's `/api/v2/*` endpoints. You need a token:

1. Open `https://<your-server>/import/api-token` in a browser (or press `g t` from any FreeWise page), click **New token**.
2. Copy the raw token (shown only once).
3. Save it:

```bash
freewise --url https://freewise.chikaki.com auth login --token fw_xxxxx
```

This writes `~/.config/freewise/config.toml` (mode 0600) so subsequent commands don't need flags.

Override per-command via `--url` / `--token`, or via env vars `FREEWISE_URL` / `FREEWISE_TOKEN`.

## Commands

### Read

```text
freewise stats                       # counts + review-due + mastered + embedded
freewise search "stoicism" [--tag T] [--limit N] [--include-discarded]
freewise recent [--limit 10]
freewise show 1234                   # full detail
freewise random [--book-id 42]       # surprise me
freewise related 1234 [--limit 10]   # semantic neighbors (needs Ollama)
```

### Discovery

```text
freewise books [--limit 50]
freewise book-highlights 42 [--limit 50]
freewise authors [query] [--limit 50]
freewise tags [query] [--limit 100]
```

### Write

```text
freewise note 1234 "this matters because..."
freewise favorite 1234 | unfavorite 1234
freewise discard 1234 | restore 1234
freewise master 1234 | unmaster 1234       # skip from review queue
freewise tag add 1234 "deep learning"      # normalized to lowercase
freewise tag remove 1234 "deep learning"
freewise tag list 1234

freewise add --text "captured quote" \
             --book "Book Title" --author "Author"
```

### Export

```text
freewise export csv -o backup.csv               # Readwise-compatible CSV
freewise export markdown -o vault.zip           # per-book .md ZIP (Obsidian/Logseq)
freewise export notion -o notion.zip            # Notion-flavored .md ZIP
freewise export atomic -o atomic.zip            # one .md per highlight
freewise export atomic --book-id 42 -o b.zip    # atomic notes for one book
freewise export csv | head                      # stdout if -o omitted
```

### Embeddings (semantic similarity)

```text
freewise embed-backfill [--batch-size 64] [--max 0] [--model X]
```

Loops the server-side backfill endpoint until no rows remain. See
`docs/SEMANTIC_SETUP.md` for Ollama setup.

Every command supports `--json` for machine-readable output.

## Using from Claude Code

The CLI is `--json`-clean for every subcommand, so Claude Code can pipe it into `jq` or parse output directly:

```bash
# "What did I highlight about X?"
freewise --json search "memoization" --limit 10 | jq '.results[].text'

# "What's due for review today?"
freewise --json stats | jq '.review_due_today'

# "Save this thought as a highlight on the book I'm currently reading"
freewise add --text "$(cat /tmp/thought.txt)" --book "Antifragile" --author "Taleb"
```

Drop a hint in your CLAUDE.md so the agent knows the tool is available:

```markdown
## Tools available
- `freewise` — query/edit highlights in the FreeWise library. `freewise --help` for usage.
```

## Output

Without `--json`, output is one-line-per-highlight for list views and a multi-line block for `show`. Stars (`★`) mark favorites, `#<id>` is the highlight ID for use in subsequent commands.

## Exit codes

- `0` — success
- `1` — server error or auth failure
- `2` — invalid argv
- `130` — interrupted (Ctrl-C)
