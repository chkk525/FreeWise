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

1. Open `https://<your-server>/api-tokens` in a browser, click **New token**.
2. Copy the raw token (shown only once).
3. Save it:

```bash
freewise --url https://freewise.chikaki.com auth login --token fw_xxxxx
```

This writes `~/.config/freewise/config.toml` (mode 0600) so subsequent commands don't need flags.

Override per-command via `--url` / `--token`, or via env vars `FREEWISE_URL` / `FREEWISE_TOKEN`.

## Commands

```text
freewise stats                       # counts + review-due summary
freewise search "stoicism"           # full-text across text + note
freewise search "x" --json           # any command supports --json
freewise recent --limit 20           # newest highlights first
freewise show 1234                   # full detail of one highlight
freewise books --limit 50            # books with highlight counts

freewise note 1234 "this matters because..."
freewise favorite 1234               # toggle on
freewise unfavorite 1234
freewise discard 1234
freewise restore 1234

freewise add --text "captured quote" \
             --book "Book Title" --author "Author"
```

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
