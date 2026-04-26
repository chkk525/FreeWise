"""FreeWise MCP server — exposes highlight tools to Claude Code via stdio MCP.

Tool surface mirrors the ``freewise`` CLI so Claude can:

- search across the whole library (text + note)
- list recent highlights
- read a single highlight in full
- update notes / favorite / discard
- create new highlights manually
- pull stats

All tools are sync. They use the existing ``freewise_cli.client.Client`` so we
only have to keep one HTTP wrapper in sync with the API.

Auth resolution mirrors the CLI: env vars (``FREEWISE_URL``, ``FREEWISE_TOKEN``)
take precedence over ``~/.config/freewise/config.toml``, with hard-coded
defaults at the bottom.
"""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from freewise_cli import config as cfg
from freewise_cli.client import Client, FreewiseError


def _client() -> Client:
    c = cfg.load()
    return Client(url=c.url, token=c.token)


def _ok(data: Any) -> str:
    """JSON-serialize a tool result so Claude gets a stable shape it can parse."""
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _err(msg: str) -> str:
    """Wrap an error in the same JSON shape so callers can branch on `error`."""
    return json.dumps({"error": msg}, ensure_ascii=False)


mcp = FastMCP("freewise-mcp")


# ── Read tools ────────────────────────────────────────────────────────────


@mcp.tool()
def freewise_search(query: str, limit: int = 20, include_discarded: bool = False) -> str:
    """Full-text search across this user's highlights (text + note).

    Returns up to `limit` matches as JSON. Discarded highlights are excluded
    by default. The query supports literal `%` and `_` — they're escaped server-side.
    """
    try:
        body = _client().search(query, page=1, page_size=limit, include_discarded=include_discarded)
    except FreewiseError as e:
        return _err(f"search failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_recent(limit: int = 10) -> str:
    """List the most recently added highlights, newest first."""
    try:
        body = _client().list_highlights(page=1, page_size=limit)
    except FreewiseError as e:
        return _err(f"recent failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_show(highlight_id: int) -> str:
    """Fetch one highlight in full by numeric id (text + book + note + flags)."""
    try:
        body = _client().get_highlight(highlight_id)
    except FreewiseError as e:
        return _err(f"show failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_stats() -> str:
    """Aggregate counts: total/active/discarded/favorited highlights, books, review-due."""
    try:
        body = _client().stats()
    except FreewiseError as e:
        return _err(f"stats failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_books(limit: int = 50) -> str:
    """List books that have at least one highlight, with counts."""
    try:
        body = _client().list_books(page=1, page_size=limit)
    except FreewiseError as e:
        return _err(f"books failed: {e}")
    return _ok(body)


# ── Write tools ───────────────────────────────────────────────────────────


@mcp.tool()
def freewise_set_note(highlight_id: int, note: str) -> str:
    """Replace the note on a highlight. Pass an empty string to clear."""
    try:
        body = _client().patch_highlight(highlight_id, note=note)
    except FreewiseError as e:
        return _err(f"set_note failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_favorite(highlight_id: int, on: bool = True) -> str:
    """Set or clear the favorite flag. `on=False` to unfavorite."""
    try:
        body = _client().patch_highlight(highlight_id, is_favorited=on)
    except FreewiseError as e:
        return _err(f"favorite failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_discard(highlight_id: int, on: bool = True) -> str:
    """Discard or restore a highlight. Discarding auto-clears the favorite flag."""
    try:
        body = _client().patch_highlight(highlight_id, is_discarded=on)
    except FreewiseError as e:
        return _err(f"discard failed: {e}")
    return _ok(body)


@mcp.tool()
def freewise_add(
    text: str,
    book: str | None = None,
    author: str | None = None,
    note: str | None = None,
    location: int | None = None,
) -> str:
    """Manually capture a new highlight. `book` is created if it doesn't exist yet."""
    try:
        body = _client().create_highlight(
            text=text, title=book, author=author, note=note, location=location,
        )
    except FreewiseError as e:
        return _err(f"add failed: {e}")
    return _ok(body)


def main() -> None:
    """Entry point used by the ``freewise-mcp`` console script."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
