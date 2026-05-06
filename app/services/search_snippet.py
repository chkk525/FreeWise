"""FTS5 highlight rendering for search results.

FTS5's :func:`highlight` returns the *full* column text with two
configurable substrings inserted around each match. We pass two sentinel
strings (chosen so they cannot appear in user-authored highlights), then
HTML-escape the entire result, then substitute the sentinels with the
actual ``<mark>`` markup. This keeps user content safe from injection
without giving up the convenience of letting Jinja render the result
with ``| safe``.

We previously used :func:`snippet` with a small token budget, which
truncated long highlights aggressively (~30-40 characters of context).
Users found that too short to skim, especially for CJK text where
trigram tokens are short. ``highlight()`` returns the entire
highlight, marks every match, and the browser handles wrapping.
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
    """Render the matching ``highlight.text`` for each rowid in ``rowids``.

    Returns a mapping ``{rowid: rendered_html}`` containing only rows
    whose result was non-empty. The HTML is the full highlight text
    with each match wrapped in a ``<mark>`` tag. If the match was
    purely in the ``note`` column the returned text has no marks, but
    the note itself is rendered separately by the caller and remains
    visible to the user.
    """
    rowid_list = list(rowids)
    if not rowid_list:
        return {}

    placeholders = ",".join(str(int(r)) for r in rowid_list)
    sql = sa_text(
        # `highlight(table, col_index, open, close)` returns the full
        # text of one column with sentinels around every match. We pick
        # column 0 (text); the schema is `highlight_fts(text, note, ...)`.
        "SELECT rowid, highlight(highlight_fts, 0, :open, :close) "
        f"FROM highlight_fts "
        f"WHERE highlight_fts MATCH :match AND rowid IN ({placeholders})"
    ).bindparams(
        open=SNIPPET_OPEN_SENTINEL,
        close=SNIPPET_CLOSE_SENTINEL,
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
