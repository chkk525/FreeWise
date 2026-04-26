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


def _call(label: str, fn):
    """Run an API-bound callable, catch any exception, return structured JSON.

    Without this guard, a transport failure (httpx.ConnectError, JSON decode
    error, missing config, etc.) would bubble up as an MCP protocol error
    and break the agent's session. With it, the agent always sees either
    success JSON or ``{"error": "..."}`` and can branch normally.
    """
    try:
        return _ok(fn())
    except FreewiseError as e:
        return _err(f"{label}: {e}")
    except Exception as e:  # noqa: BLE001 — last-resort guard for transport/config failures
        return _err(f"{label}: {type(e).__name__}: {e}")


mcp = FastMCP("freewise-mcp")


# ── Read tools ────────────────────────────────────────────────────────────


@mcp.tool()
def freewise_search(
    query: str,
    limit: int = 20,
    include_discarded: bool = False,
    tag: str | None = None,
) -> str:
    """Full-text search across this user's highlights (text + note).

    Returns up to `limit` matches as JSON. Discarded highlights are excluded
    by default. The query supports literal `%` and `_` — they're escaped
    server-side. Pass `tag` to additionally filter to highlights carrying
    that exact tag (case-insensitive).
    """
    return _call("search failed", lambda: _client().search(
        query, page=1, page_size=limit, include_discarded=include_discarded, tag=tag,
    ))


@mcp.tool()
def freewise_recent(limit: int = 10) -> str:
    """List the most recently added highlights, newest first."""
    return _call("recent failed", lambda: _client().list_highlights(page=1, page_size=limit))


@mcp.tool()
def freewise_show(highlight_id: int) -> str:
    """Fetch one highlight in full by numeric id (text + book + note + flags)."""
    return _call("show failed", lambda: _client().get_highlight(highlight_id))


@mcp.tool()
def freewise_summarize_book(book_id: int, question: str | None = None, top_k: int = 12) -> str:
    """RAG summary of one book using its highlights as evidence.

    Optional ``question`` overrides the default "summarize key themes"
    prompt. Useful for "what advice does this book give about X" style
    follow-ups. Requires Ollama + backfill (see SEMANTIC_SETUP.md).
    """
    return _call(
        "summarize_book failed",
        lambda: _client().summarize_book(book_id, question=question, top_k=top_k),
    )


@mcp.tool()
def freewise_tag_rename(old_name: str, new_name: str) -> str:
    """Rename a tag globally. 409 if the new name collides — use
    ``freewise_tag_merge`` instead. Reserved names (favorite/discard)
    are rejected. Returns the renamed tag's summary."""
    return _call(
        "tag_rename failed",
        lambda: _client().rename_tag(old_name, new_name),
    )


@mcp.tool()
def freewise_tag_merge(src: str, into: str) -> str:
    """Merge tag ``src`` into ``into`` — every highlight that had ``src``
    gets ``into`` (skipping duplicates), and the source Tag is deleted.
    Useful for consolidating near-duplicates ('ml' + 'machine learning')."""
    return _call(
        "tag_merge failed",
        lambda: _client().merge_tag(src, into),
    )


@mcp.tool()
def freewise_author_rename(old_name: str, new_name: str) -> str:
    """Rename an author across every book that has it. Useful for
    fixing import-time typos. Returns the new author's summary
    (book count + highlight count)."""
    return _call(
        "author_rename failed",
        lambda: _client().rename_author(old_name, new_name),
    )


@mcp.tool()
def freewise_ask(question: str, top_k: int = 8) -> str:
    """RAG: ask a natural-language question over your highlight library.

    The server embeds the question, retrieves the top-K most similar
    highlights, then asks an Ollama generate model to compose a
    citation-grounded answer (each claim cited as ``[#id]``).

    Returns a JSON object with ``answer`` (markdown text), ``citations``
    (the highlights used, with similarity scores), ``embed_model``,
    ``generate_model``, and ``truncated`` (true if the citation block
    was clipped to fit the prompt budget).

    Requires Ollama to be reachable AND embeddings to have been
    backfilled — see docs/SEMANTIC_SETUP.md. Returns ``{"error": ...}``
    if either is missing.
    """
    return _call(
        "ask failed",
        lambda: _client().ask(question, top_k=top_k),
    )


@mcp.tool()
def freewise_suggest_tags(highlight_id: int, neighbors: int = 20, limit: int = 5) -> str:
    """Suggest tags for a highlight by inspecting its semantic neighbors.

    Pulls the top-K most-similar highlights, harvests their tags, ranks
    by cosine-weighted frequency, and returns the top suggestions —
    skipping reserved names and tags the source already has. Requires
    embeddings to be backfilled.

    Useful for: "I just captured this thought, what existing tags from
    my library would fit it?"
    """
    return _call(
        "suggest_tags failed",
        lambda: _client().suggest_tags(highlight_id, neighbors=neighbors, limit=limit),
    )


@mcp.tool()
def freewise_related(highlight_id: int, limit: int = 10) -> str:
    """Top-K semantically similar highlights to ``highlight_id``.

    Backed by Ollama embeddings (must have been backfilled — returns
    ``count: 0`` if not). Useful for "show me other thoughts I've had
    on this same theme" prompts. The source highlight itself is excluded.
    """
    return _call(
        "related failed",
        lambda: _client().related_highlights(highlight_id, limit=limit),
    )


@mcp.tool()
def freewise_semantic_dupes(threshold: float = 0.92, limit: int = 100) -> str:
    """Find paraphrase / same-idea highlight pairs via embedding cosine.

    Complements ``freewise_duplicates`` (prefix match): semantic dedup
    catches paraphrases and same-idea repeats across different books
    that prefix matching can't see. Requires Ollama embeddings to be
    backfilled — returns ``count: 0`` until then.

    The default threshold of 0.92 is fairly strict; lower it (e.g. 0.85)
    for fuzzier matches.
    """
    return _call(
        "semantic_dupes failed",
        lambda: _client().find_semantic_duplicates(threshold=threshold, limit=limit),
    )


@mcp.tool()
def freewise_duplicates(prefix_chars: int = 80, min_group_size: int = 2, limit: int = 50) -> str:
    """Find probable duplicate highlights by leading-character match.

    Useful after re-importing the same Kindle book — the second import
    creates highlights with identical text but different ids. Returns
    groups of highlights sharing the same first ``prefix_chars`` of text.

    Each group has ``count`` and ``members`` (sorted by id ascending so
    you can keep the oldest and discard the rest).
    """
    return _call(
        "duplicates failed",
        lambda: _client().find_duplicates(
            prefix_chars=prefix_chars, min_group_size=min_group_size, limit=limit,
        ),
    )


@mcp.tool()
def freewise_today(salt: str | None = None) -> str:
    """Stable "highlight of the day" — same row for all callers today.

    Different from ``freewise_random`` (which changes per call). Useful
    for daily-focus prompts: "What's my highlight of the day, and what
    other highlights in my library connect to it?"
    Pass ``salt`` (e.g. "morning") to get a different stable pick within
    the same day.
    """
    return _call(
        "today failed",
        lambda: _client().today_highlight(salt=salt),
    )


@mcp.tool()
def freewise_random(book_id: int | None = None) -> str:
    """Return one random highlight from the user's library — "surprise me".

    Optional ``book_id`` scopes to a single book. Mastered highlights are
    included by default (mastery hides from review, not from serendipity).
    """
    return _call("random failed", lambda: _client().random_highlight(book_id=book_id))


@mcp.tool()
def freewise_stats() -> str:
    """Aggregate counts: total/active/discarded/favorited highlights, books, review-due."""
    return _call("stats failed", lambda: _client().stats())


@mcp.tool()
def freewise_health() -> str:
    """Lightweight liveness probe: status + active/embedded counts + Ollama reachability.

    Useful for "is the FreeWise server up and is C2 backfilled" check
    from a Claude Code conversation. No auth required by the underlying
    /healthz endpoint."""
    return _call("health failed", lambda: _client().healthz())


@mcp.tool()
def freewise_books(limit: int = 50) -> str:
    """List books that have at least one highlight, with counts."""
    return _call("books failed", lambda: _client().list_books(page=1, page_size=limit))


@mcp.tool()
def freewise_book_highlights(book_id: int, limit: int = 50) -> str:
    """List highlights for one specific book.

    Useful when Claude needs to discuss a particular book — first call
    ``freewise_books`` to find the id, then this tool to pull the actual
    highlights.
    """
    return _call(
        "book_highlights failed",
        lambda: _client().list_highlights(page=1, page_size=limit, book_id=book_id),
    )


@mcp.tool()
def freewise_tags(query: str | None = None, limit: int = 100) -> str:
    """List all highlight-level tags with usage counts.

    Sorted by highlight_count desc; the legacy "favorite"/"discard"
    pseudo-tags are filtered out. Optional ``query`` substring-filters
    the tag name. Useful for discovering what topics the user has tagged
    before deciding what tag to filter search by.
    """
    return _call(
        "tags failed",
        lambda: _client().list_tag_summary(page=1, page_size=limit, q=query),
    )


@mcp.tool()
def freewise_authors(query: str | None = None, limit: int = 50) -> str:
    """List distinct authors with book + highlight counts.

    Sorted by highlight_count desc so the heaviest-quoted authors come
    first. Optional ``query`` substring-filters the author name. Useful
    when Claude needs to discover which authors the user has read,
    before drilling into a specific book or filtering search.
    """
    return _call(
        "authors failed",
        lambda: _client().list_authors(page=1, page_size=limit, q=query),
    )


# ── Write tools ───────────────────────────────────────────────────────────


@mcp.tool()
def freewise_set_note(highlight_id: int, note: str) -> str:
    """Replace the note on a highlight. Pass an empty string to clear."""
    return _call("set_note failed", lambda: _client().patch_highlight(highlight_id, note=note))


@mcp.tool()
def freewise_append_note(highlight_id: int, text: str) -> str:
    """Append ``text`` to the highlight's existing note (preserves prior content).

    Distinct from ``freewise_set_note`` which replaces. Useful for adding
    follow-up thoughts during review without losing the original note.
    Inserts a blank-line separator between the old note and the new text.
    """
    return _call(
        "append_note failed",
        lambda: _client().append_note(highlight_id, text),
    )


@mcp.tool()
def freewise_favorite(highlight_id: int, on: bool = True) -> str:
    """Set or clear the favorite flag. `on=False` to unfavorite."""
    return _call("favorite failed", lambda: _client().patch_highlight(highlight_id, is_favorited=on))


@mcp.tool()
def freewise_discard(highlight_id: int, on: bool = True) -> str:
    """Discard or restore a highlight. Discarding auto-clears the favorite flag."""
    return _call("discard failed", lambda: _client().patch_highlight(highlight_id, is_discarded=on))


@mcp.tool()
def freewise_master(highlight_id: int, on: bool = True) -> str:
    """Mark/unmark a highlight as mastered.

    Mastered highlights are excluded from the spaced-repetition review
    queue but remain visible in library, search, and exports. Pass
    ``on=False`` to bring a row back into review.
    """
    return _call("master failed", lambda: _client().patch_highlight(highlight_id, is_mastered=on))


@mcp.tool()
def freewise_tag_list(highlight_id: int) -> str:
    """List the tags currently attached to a highlight."""
    return _call("tag_list failed", lambda: _client().list_tags(highlight_id))


@mcp.tool()
def freewise_tag_add(highlight_id: int, tag: str) -> str:
    """Attach a tag to a highlight. Idempotent — re-adding is a no-op.

    Tag names are normalized to lowercase + collapsed whitespace server-side.
    The names ``favorite`` and ``discard`` are reserved and rejected with 400.
    """
    return _call("tag_add failed", lambda: _client().add_tag(highlight_id, tag))


@mcp.tool()
def freewise_tag_remove(highlight_id: int, tag: str) -> str:
    """Remove a tag from a highlight. Idempotent."""
    return _call("tag_remove failed", lambda: _client().remove_tag(highlight_id, tag))


@mcp.tool()
def freewise_add(
    text: str,
    book: str | None = None,
    author: str | None = None,
    note: str | None = None,
    location: int | None = None,
) -> str:
    """Manually capture a new highlight. `book` is created if it doesn't exist yet."""
    return _call("add failed", lambda: _client().create_highlight(
        text=text, title=book, author=author, note=note, location=location,
    ))


def main() -> None:
    """Entry point used by the ``freewise-mcp`` console script."""
    mcp.run(transport="stdio")


if __name__ == "__main__":  # pragma: no cover
    main()
