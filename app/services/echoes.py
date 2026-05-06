"""Dashboard "Echoes" widget — natural review nudges + re-read sparks.

The widget shows up to N cards on the dashboard, drawn from three
distinct sources so the user gets variety even on slow days:

1. **Anniversary** — a highlight created on this calendar date 1, 2, or
   3 years ago. Surfacing the past at exactly its anniversary feels
   serendipitous; same-day-different-year is a stronger trigger than
   "n days ago" because it lines up with how human memory cues work.

2. **Long-time-no-see** — a highlight from a book the user hasn't
   reviewed in 60+ days. Emphasises *book*-level neglect over highlight-
   level neglect: re-reading one quote from a long-shelved book is a
   bigger spark than a quote from a book they reviewed yesterday.

3. **Re-read targets** — highlights where the user explicitly tapped
   📖 ("read this book again"). Highest signal: the user already opted
   in to wanting more from this book.

Sources are de-duplicated by highlight_id and capped at the requested
total. If a source has nothing to offer (fresh install, no neglect,
no reread targets), the function silently returns whatever's left from
the other sources — never errors out.

Single-user app, so user_id=1 is hard-coded just like every other
read path in this module. Adding multi-user is one parameter change.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlmodel import Session, select

from app.models import Book, Highlight


# How many days a book must have been silent before the "long time no
# see" branch surfaces it. 60 days is roughly 2× the median forgetting-
# curve relapse interval — long enough to feel "rediscovered," short
# enough that an actively-used library still produces hits.
NEGLECT_THRESHOLD_DAYS = 60

# Years to look back for the anniversary branch. Three years gives us
# enough material on a multi-year library without surfacing the same
# highlight twice on a single-year-old library.
ANNIVERSARY_YEARS = (1, 2, 3)


EchoSource = Literal["anniversary", "neglect", "reread"]


@dataclass(frozen=True)
class Echo:
    """One card in the Echoes widget."""

    source: EchoSource
    highlight: Highlight
    book: Book | None
    # Human-readable context: "1年前", "60日ぶり", "もう一度読みたい本から".
    # Templates render this verbatim — i18n lives at the call site.
    label: str
    # For anniversary cards: how many years ago. None for other sources.
    years_ago: int | None = None
    # For neglect cards: days since the book was last reviewed.
    days_since: int | None = None


def get_echoes(
    session: Session,
    *,
    today: date | None = None,
    limit: int = 3,
) -> list[Echo]:
    """Return up to `limit` Echo cards drawn from all three sources.

    `today` is injectable so tests can pin the date without touching the
    clock. Production callers leave it as None and we read UTC now.

    Order: anniversary first (strongest temporal cue), then reread
    targets (strongest user signal), then neglect (filler). Within each
    source we randomize at the SQL layer so two refreshes don't show
    the same card.
    """
    if today is None:
        today = datetime.now(timezone.utc).date()
    if limit <= 0:
        return []

    seen: set[int] = set()
    out: list[Echo] = []

    # 1) Anniversary — same month + day, prior years.
    for years in ANNIVERSARY_YEARS:
        if len(out) >= limit:
            break
        echo = _pick_anniversary(session, today, years, exclude=seen)
        if echo is not None and echo.highlight.id is not None:
            seen.add(echo.highlight.id)
            out.append(echo)

    # 2) Reread targets — user-flagged 📖.
    if len(out) < limit:
        for echo in _pick_reread_targets(session, exclude=seen, limit=limit - len(out)):
            if echo.highlight.id is not None:
                seen.add(echo.highlight.id)
                out.append(echo)

    # 3) Neglect — books silent ≥ NEGLECT_THRESHOLD_DAYS.
    if len(out) < limit:
        for echo in _pick_neglected(session, today, exclude=seen, limit=limit - len(out)):
            if echo.highlight.id is not None:
                seen.add(echo.highlight.id)
                out.append(echo)

    return out


# ── Source pickers ──────────────────────────────────────────────────────


def _pick_anniversary(
    session: Session,
    today: date,
    years_ago: int,
    *,
    exclude: set[int],
) -> Echo | None:
    """Pick one highlight created `years_ago` years ago today."""
    target_year = today.year - years_ago
    # Handle Feb 29 → Feb 28 fallback so the query never raises on a
    # non-leap target year.
    try:
        target_date = date(target_year, today.month, today.day)
    except ValueError:
        target_date = date(target_year, today.month, 28)

    # Created_at is stored as a naïve UTC datetime; compare as a day-
    # range bracket so the index range scan still applies.
    start = datetime.combine(target_date, datetime.min.time())
    end = datetime.combine(target_date + timedelta(days=1), datetime.min.time())

    from sqlalchemy import func as sa_func

    stmt = (
        select(Highlight)
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(Highlight.created_at >= start)
        .where(Highlight.created_at < end)
        .order_by(sa_func.random())
        .limit(5)
    )
    for highlight in session.exec(stmt).all():
        if highlight.id is None or highlight.id in exclude:
            continue
        book = session.get(Book, highlight.book_id) if highlight.book_id else None
        years_label = "1年前" if years_ago == 1 else f"{years_ago}年前"
        return Echo(
            source="anniversary",
            highlight=highlight,
            book=book,
            label=years_label,
            years_ago=years_ago,
        )
    return None


def _pick_reread_targets(
    session: Session,
    *,
    exclude: set[int],
    limit: int,
) -> list[Echo]:
    """Pick highlights flagged 📖 by the user, randomized."""
    if limit <= 0:
        return []

    from sqlalchemy import func as sa_func

    stmt = (
        select(Highlight)
        .where(Highlight.user_id == 1)
        .where(Highlight.is_reread_target == True)  # noqa: E712
        .where(Highlight.is_discarded == False)  # noqa: E712
        .order_by(sa_func.random())
        .limit(limit + len(exclude) + 5)  # over-fetch for exclusion
    )
    out: list[Echo] = []
    for highlight in session.exec(stmt).all():
        if len(out) >= limit:
            break
        if highlight.id is None or highlight.id in exclude:
            continue
        book = session.get(Book, highlight.book_id) if highlight.book_id else None
        out.append(
            Echo(
                source="reread",
                highlight=highlight,
                book=book,
                label="もう一度読みたい本から",
            )
        )
    return out


def _pick_neglected(
    session: Session,
    today: date,
    *,
    exclude: set[int],
    limit: int,
) -> list[Echo]:
    """Pick highlights from books with no review activity ≥ N days."""
    if limit <= 0:
        return []

    cutoff = datetime.combine(today - timedelta(days=NEGLECT_THRESHOLD_DAYS), datetime.min.time())

    from sqlalchemy import func as sa_func

    # last_reviewed_at NULL = never reviewed. Treat NULL as "neglected"
    # because a never-reviewed book is the most extreme form of neglect
    # and is exactly the case we want to surface for someone who imported
    # a big batch and forgot about it.
    stmt = (
        select(Highlight)
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(Highlight.is_mastered == False)  # noqa: E712
        .where(
            (Highlight.last_reviewed_at.is_(None))
            | (Highlight.last_reviewed_at < cutoff)
        )
        .order_by(sa_func.random())
        .limit(limit + len(exclude) + 5)
    )
    out: list[Echo] = []
    for highlight in session.exec(stmt).all():
        if len(out) >= limit:
            break
        if highlight.id is None or highlight.id in exclude:
            continue
        book = session.get(Book, highlight.book_id) if highlight.book_id else None
        if highlight.last_reviewed_at is None:
            label = "久しぶりにこの一冊から"
            days_since = None
        else:
            days_since = (
                today - highlight.last_reviewed_at.date()
            ).days
            label = f"{days_since}日ぶり"
        out.append(
            Echo(
                source="neglect",
                highlight=highlight,
                book=book,
                label=label,
                days_since=days_since,
            )
        )
    return out
