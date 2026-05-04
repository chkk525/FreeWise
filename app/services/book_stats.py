"""Per-book aggregate stats for the book-detail page.

Single-query helpers that the template can render without N+1. Counts +
date range come from the highlight rows; tag distribution comes from
HighlightTag joined with Tag. ``review_count`` and ``last_reviewed_at``
are already on Highlight rows so we just aggregate them in SQL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlalchemy import case, func
from sqlmodel import Session, select

from app.models import Highlight, HighlightTag, Tag


@dataclass(frozen=True)
class BookStats:
    """Read-only aggregate snapshot for one book.

    All counts are derived from rows in `highlight` for the given book.
    Counts split active/discarded so the template doesn't need to do
    arithmetic. ``avg_highlight_length`` rounds to the nearest int and
    is None when the book has zero highlights. Date fields are None
    when the underlying highlights have no ``created_at``.
    """
    active_count: int = 0
    discarded_count: int = 0
    favorited_count: int = 0
    mastered_count: int = 0
    avg_highlight_length: Optional[int] = None
    earliest_highlight_at: Optional[datetime] = None
    latest_highlight_at: Optional[datetime] = None
    last_reviewed_at: Optional[datetime] = None
    total_review_count: int = 0
    top_tags: list[tuple[str, int]] = field(default_factory=list)

    @property
    def total_count(self) -> int:
        return self.active_count + self.discarded_count

    @property
    def mastered_fraction(self) -> float:
        """Fraction of active highlights marked mastered (0.0 — 1.0)."""
        if self.active_count == 0:
            return 0.0
        return self.mastered_count / self.active_count


def compute_book_stats(session: Session, book_id: int) -> BookStats:
    """Aggregate stats for one book in a small constant number of queries.

    Uses two SQL round-trips:
      1. One aggregate over highlight rows (counts + min/max + sums + avg).
      2. One aggregate over HighlightTag joined with Tag for the top-tag
         pivot — limited to the top 3 by count.

    The numeric fields default to 0 / None on an empty book so the
    caller doesn't need to special-case "no highlights yet".
    """
    row = session.exec(
        select(
            func.count(Highlight.id),
            func.sum(
                case((Highlight.is_discarded == False, 1), else_=0)  # noqa: E712
            ),
            func.sum(
                case((Highlight.is_discarded == True, 1), else_=0)  # noqa: E712
            ),
            func.sum(
                case(
                    (
                        (Highlight.is_discarded == False)  # noqa: E712
                        & (Highlight.is_favorited == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        (Highlight.is_discarded == False)  # noqa: E712
                        & (Highlight.is_mastered == True),  # noqa: E712
                        1,
                    ),
                    else_=0,
                )
            ),
            func.avg(func.length(Highlight.text)),
            func.min(Highlight.created_at),
            func.max(Highlight.created_at),
            func.max(Highlight.last_reviewed_at),
            func.sum(Highlight.review_count),
        ).where(Highlight.book_id == book_id)
    ).one()

    (
        total,
        active,
        discarded,
        favorited,
        mastered,
        avg_len,
        min_at,
        max_at,
        last_review,
        review_sum,
    ) = row

    if not total:
        return BookStats()

    top_rows = session.exec(
        select(Tag.name, func.count(HighlightTag.tag_id).label("c"))
        .join(HighlightTag, HighlightTag.tag_id == Tag.id)
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(Highlight.book_id == book_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(Tag.name)
        .order_by(func.count(HighlightTag.tag_id).desc(), Tag.name.asc())
        .limit(3)
    ).all()

    return BookStats(
        active_count=int(active or 0),
        discarded_count=int(discarded or 0),
        favorited_count=int(favorited or 0),
        mastered_count=int(mastered or 0),
        avg_highlight_length=int(round(avg_len)) if avg_len is not None else None,
        earliest_highlight_at=min_at,
        latest_highlight_at=max_at,
        last_reviewed_at=last_review,
        total_review_count=int(review_sum or 0),
        top_tags=[(name, int(count)) for name, count in top_rows],
    )
