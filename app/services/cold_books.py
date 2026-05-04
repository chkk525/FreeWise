"""Re-engagement surface: books with the most stale interaction history.

A book is "cold" when its newest review-action timestamp is the oldest
across the library — i.e. the user hasn't touched any of its highlights
in the longest time. Books that have *never* been touched at all sort
ahead of touched-but-stale books so the long tail of imports surfaces
first.

"Touched" combines two signals:
  * ``Highlight.last_reviewed_at`` — bumped whenever a highlight is
    marked done in the review flow, including pre-ReviewLog history.
  * Newest ``ReviewLog.at`` row for each highlight — covers all the
    new verbs (favorite/discard/master/...) that the listener captures.

Discarded highlights are ignored: a book whose only remaining
highlights were discarded shouldn't be surfaced as "needs attention."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Book, Highlight, ReviewLog


@dataclass(frozen=True)
class ColdBookEntry:
    """One row of the dashboard cold-books widget."""
    id: int
    title: str
    author: Optional[str]
    cover_image_url: Optional[str]
    active_highlights: int
    last_touched_at: Optional[datetime]


def cold_books(
    session: Session,
    *,
    limit: int = 5,
    user_id: int = 1,
) -> list[ColdBookEntry]:
    """Return up to ``limit`` books ordered by oldest interaction first.

    Books with no recorded interactions sort ahead of touched books
    (NULLS FIRST is faked via a sentinel sort key). Books with zero
    active highlights are excluded.
    """
    # Per-highlight latest action: the MAX of last_reviewed_at and the
    # newest review_log row for that highlight. LEFT JOIN keeps
    # highlights that have never been logged.
    rl_subq = (
        select(
            ReviewLog.highlight_id.label("hl_id"),
            func.max(ReviewLog.at).label("rl_max"),
        )
        .group_by(ReviewLog.highlight_id)
        .subquery()
    )
    # SQLite-friendly per-highlight latest = MAX over the two values via
    # CASE since SQLite has no GREATEST function. CASE returns NULL when
    # both inputs are NULL.
    last_touched = func.max(
        func.coalesce(
            func.max(Highlight.last_reviewed_at, rl_subq.c.rl_max),
            Highlight.last_reviewed_at,
            rl_subq.c.rl_max,
        )
    ).label("last_touched")

    stmt = (
        select(
            Book.id,
            Book.title,
            Book.author,
            Book.cover_image_url,
            func.count(Highlight.id).label("active_count"),
            last_touched,
        )
        .join(Highlight, Highlight.book_id == Book.id)
        .outerjoin(rl_subq, rl_subq.c.hl_id == Highlight.id)
        .where(Highlight.user_id == user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(Book.id, Book.title, Book.author, Book.cover_image_url)
        .having(func.count(Highlight.id) > 0)
        # NULLs first via a CASE-coalesce sentinel: rows with no
        # interaction sort before any real timestamp because '0000-01-01'
        # < every real date string. SQLite lex-compares the ISO strings.
        .order_by(
            func.coalesce(last_touched, "0000-01-01").asc(),
            Book.id.asc(),
        )
        .limit(limit)
    )

    rows = list(session.exec(stmt).all())
    return [
        ColdBookEntry(
            id=int(b_id),
            title=title,
            author=author,
            cover_image_url=cover,
            active_highlights=int(count),
            last_touched_at=touched,
        )
        for (b_id, title, author, cover, count, touched) in rows
    ]
