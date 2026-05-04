"""FTS5 snippet rendering for search results.

FTS5's :func:`snippet` returns a copy of the column text with two
configurable substrings inserted around each match. We pass two sentinel
strings (chosen so they cannot appear in user-authored highlights), then
HTML-escape the entire snippet, then substitute the sentinels with the
actual ``<mark>`` markup. This keeps user content safe from injection
without giving up the convenience of letting Jinja render the result
with ``| safe``.
"""
from __future__ import annotations

import html
from typing import Iterable

from sqlalchemy import text as sa_text
from sqlmodel import Session


# Control characters wrapped in unique tokens — high enough collision
# resistance that a user pasting them verbatim is not a realistic concern.
# If this ever did collide, the worst case is missing markup, not XSS.
SNIPPET_OPEN_SENTINEL = "\x02FW_SNIP_OPEN\x02"
SNIPPET_CLOSE_SENTINEL = "\x03FW_SNIP_CLOSE\x03"

# Number of tokens the snippet may include around a match. Trigram FTS5
# treats each character trigram as a "token", so 32 tokens is roughly
# 30-40 chars of context — enough to skim, short enough to scan.
_SNIPPET_TOKEN_BUDGET = 32

# CSS classes applied to the rendered <mark>. Tailwind utility names so
# the result is consistent with the rest of the UI light/dark theming.
_MARK_OPEN = '<mark class="bg-yellow-200 dark:bg-yellow-800/60 text-inherit rounded px-0.5">'
_MARK_CLOSE = "</mark>"


def fetch_snippets(
    session: Session,
    *,
    rowids: Iterable[int],
    match_query: str,
) -> dict[int, str]:
    """Run FTS5 ``snippet()`` for each rowid that matched ``match_query``.

    Returns a mapping ``{rowid: rendered_html_snippet}`` containing only
    rows whose snippet was non-empty. Rows whose match was in the
    ``note`` column rather than ``text`` get a snippet built from
    whichever side actually matched (FTS5 picks automatically when
    column index is ``-1``).
    """
    rowid_list = list(rowids)
    if not rowid_list:
        return {}

    placeholders = ",".join(str(int(r)) for r in rowid_list)
    sql = sa_text(
        "SELECT rowid, snippet(highlight_fts, -1, :open, :close, '…', :budget) "
        f"FROM highlight_fts "
        f"WHERE highlight_fts MATCH :match AND rowid IN ({placeholders})"
    ).bindparams(
        open=SNIPPET_OPEN_SENTINEL,
        close=SNIPPET_CLOSE_SENTINEL,
        budget=_SNIPPET_TOKEN_BUDGET,
        match=match_query,
    )
    out: dict[int, str] = {}
    for rowid, raw in session.exec(sql).all():
        if not raw:
            continue
        out[int(rowid)] = render(raw)
    return out


def render(raw_snippet: str) -> str:
    """Convert a sentinel-wrapped FTS5 snippet to a safe HTML fragment."""
    escaped = html.escape(raw_snippet)
    return (
        escaped
        .replace(html.escape(SNIPPET_OPEN_SENTINEL), _MARK_OPEN)
        .replace(html.escape(SNIPPET_CLOSE_SENTINEL), _MARK_CLOSE)
    )
