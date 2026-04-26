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

## Tools (18)

### Read

| Tool                       | Purpose                                                |
|----------------------------|--------------------------------------------------------|
| `freewise_search`          | Full-text search across text + note (`tag` filter opt) |
| `freewise_recent`          | Most recent highlights, newest first                   |
| `freewise_show`            | Single highlight detail by id                          |
| `freewise_random`          | One random highlight (surprise me)                     |
| `freewise_related`         | Top-K semantically similar highlights (needs Ollama)   |
| `freewise_stats`           | Counts + review-due summary                            |

### Discovery / pivots

| Tool                       | Purpose                                                |
|----------------------------|--------------------------------------------------------|
| `freewise_books`           | Books that have at least one highlight                 |
| `freewise_book_highlights` | All highlights for one book                            |
| `freewise_authors`         | Distinct authors with book + highlight counts          |
| `freewise_tags`            | Distinct tags with usage counts                        |
| `freewise_tag_list`        | Tags currently on one highlight                        |

### Write

| Tool                       | Purpose                                                |
|----------------------------|--------------------------------------------------------|
| `freewise_set_note`        | Replace the note (empty string clears)                 |
| `freewise_favorite`        | Set or clear the favorited flag                        |
| `freewise_discard`         | Discard or restore a highlight                         |
| `freewise_master`          | Mark/unmark a highlight as mastered (skip in review)   |
| `freewise_add`             | Capture a new highlight (book auto-created if missing) |
| `freewise_tag_add`         | Attach a tag (idempotent; lowercased server-side)      |
| `freewise_tag_remove`      | Remove a tag (idempotent)                              |

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
