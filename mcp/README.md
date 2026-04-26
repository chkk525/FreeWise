# `freewise-mcp` — Model Context Protocol server for FreeWise

Exposes your FreeWise highlights to Claude Code (and any MCP host) as a set of stdio tools.

## Install

```bash
uv pip install -e mcp/
# or pip install -e mcp/  (the package depends on freewise-cli; the path source
# in mcp/pyproject.toml resolves it from ../cli)
```

This puts a `freewise-mcp` console script on `$PATH`.

## Auth

The server reuses the CLI's config and env vars:

- `FREEWISE_URL` and `FREEWISE_TOKEN` env vars take precedence
- otherwise reads `~/.config/freewise/config.toml` (created by `freewise auth login`)

So you can run `freewise auth login --url ... --token ...` once and the MCP server picks it up automatically.

## Register with Claude Code

Add to `~/.claude.json` (or use `/mcp` in Claude Code to manage):

```jsonc
{
  "mcpServers": {
    "freewise": {
      "type": "stdio",
      "command": "freewise-mcp",
      "args": [],
      "env": {
        "FREEWISE_URL": "https://freewise.chikaki.com",
        "FREEWISE_TOKEN": "fw_xxxxx"
      }
    }
  }
}
```

Restart Claude Code. The 9 tools below appear under the `freewise` namespace.

## Tools

| Tool                  | Purpose                                                   |
|-----------------------|-----------------------------------------------------------|
| `freewise_search`     | Full-text search across text + note                       |
| `freewise_recent`     | Most recent highlights, newest first                      |
| `freewise_show`       | Single highlight detail by id                             |
| `freewise_stats`      | Counts + review-due summary                               |
| `freewise_books`      | Books that have at least one highlight                    |
| `freewise_set_note`   | Replace the note on a highlight                           |
| `freewise_favorite`   | Set or clear the favorited flag                           |
| `freewise_discard`    | Discard or restore a highlight                            |
| `freewise_add`        | Capture a new highlight (book auto-created if missing)    |

All tools return JSON strings. Errors are wrapped as `{"error": "..."}` so the calling agent can branch on the shape rather than catching exceptions.

## Use from Claude Code

Once registered, ask Claude things like:

- "Search my FreeWise highlights for memoization patterns."
- "What did I highlight from Antifragile last month?"
- "Add this thought as a highlight under 'Designing Data-Intensive Applications'."
- "Show me highlight #1234 and add a note tying it to the conversation."

Claude calls the tools directly — no shell-out, no piping.

## Running the server manually

For debugging:

```bash
freewise-mcp           # listens on stdin/stdout for MCP messages
```

Tools can also be exercised in Python without the transport (useful for ad-hoc scripts):

```python
import freewise_mcp.server as s
print(s.freewise_stats())
```
