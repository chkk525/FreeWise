"""Capture and query the per-highlight review-action log.

The capture side is a single SQLAlchemy ``before_flush`` listener that
inspects dirty :class:`Highlight` rows and appends a
:class:`ReviewLog` row for each meaningful state transition. Wiring
into individual route handlers is intentionally avoided — the matrix
of HTML/HTMX, JSON API, ``/api/v2`` and bulk surfaces is too easy to
forget. The listener runs once per flush, regardless of how the
mutation arrived.

Read-side helpers power the dashboard activity widget and
``GET /api/v2/review-log``. Both are read-only and side-effect-free.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta, UTC
from typing import Iterable, Optional

from sqlalchemy import event
from sqlalchemy.orm import Session as SASession
from sqlalchemy.orm.attributes import get_history
from sqlmodel import Session, select

from app.models import Book, Highlight, ReviewLog


# ── Capture listener ────────────────────────────────────────────────────────


# (column_name, transition_to_value, action_label) — only fired when the
# attribute history shows a real previous value (i.e. the row already
# existed) AND the new value matches ``transition_to_value``. New inserts
# don't generate log rows because their "history" has no prior side.
_BOOL_TRANSITIONS: tuple[tuple[str, bool, str], ...] = (
    ("is_favorited", True, "favorite"),
    ("is_favorited", False, "unfavorite"),
    ("is_discarded", True, "discard"),
    ("is_discarded", False, "restore"),
    ("is_mastered", True, "master"),
    ("is_mastered", False, "unmaster"),
)


def _attr_changed_to(highlight: Highlight, attr: str, target_value) -> bool:
    """True iff ``attr`` was just set to ``target_value`` and previously
    held a different value (i.e. this is an update, not a fresh INSERT)."""
    history = get_history(highlight, attr)
    if not history.deleted:
        # No prior state — this is an INSERT or a no-op set on an
        # unloaded attribute. Either way, don't log.
        return False
    previous = history.deleted[0]
    current = history.added[0] if history.added else getattr(highlight, attr)
    return previous != target_value and current == target_value


def _last_reviewed_changed(highlight: Highlight) -> bool:
    """True iff ``last_reviewed_at`` was just bumped to a new datetime."""
    history = get_history(highlight, "last_reviewed_at")
    if not history.added:
        return False
    new_value = history.added[0]
    if new_value is None:
        return False
    if not history.deleted:
        return False
    previous = history.deleted[0]
    return previous != new_value


def _entries_for_dirty_highlight(highlight: Highlight) -> list[ReviewLog]:
    """Compute the ReviewLog rows that should be appended for one dirty
    Highlight in this flush. Returns an empty list when nothing material
    changed."""
    if highlight.id is None or highlight.user_id is None:
        return []
    out: list[ReviewLog] = []
    when = datetime.now(UTC).replace(tzinfo=None)
    if _last_reviewed_changed(highlight):
        out.append(
            ReviewLog(
                highlight_id=highlight.id,
                user_id=highlight.user_id,
                action="done",
                at=when,
            )
        )
    for attr, target, label in _BOOL_TRANSITIONS:
        if _attr_changed_to(highlight, attr, target):
            out.append(
                ReviewLog(
                    highlight_id=highlight.id,
                    user_id=highlight.user_id,
                    action=label,
                    at=when,
                )
            )
    return out


def _before_flush(session: SASession, flush_context, instances) -> None:
    """SQLAlchemy hook: append ReviewLog rows for every state-changing
    Highlight in this flush."""
    new_entries: list[ReviewLog] = []
    for obj in list(session.dirty):
        if isinstance(obj, Highlight):
            new_entries.extend(_entries_for_dirty_highlight(obj))
    for entry in new_entries:
        session.add(entry)


_LISTENER_REGISTERED = False


def install_listener() -> None:
    """Idempotently attach the ``before_flush`` listener.

    Called from the FastAPI lifespan hook. Safe to call from tests
    too — re-registering the same listener is a no-op."""
    global _LISTENER_REGISTERED
    if _LISTENER_REGISTERED:
        return
    event.listen(SASession, "before_flush", _before_flush)
    _LISTENER_REGISTERED = True


# ── Read helpers ────────────────────────────────────────────────────────────


def recent_entries(
    session: Session,
    *,
    user_id: int = 1,
    since: Optional[datetime] = None,
    actions: Optional[Iterable[str]] = None,
    limit: int = 200,
) -> list[ReviewLog]:
    """Return ReviewLog rows newest-first, filtered by user_id, optional
    ``since`` cutoff, and optional ``actions`` whitelist."""
    stmt = (
        select(ReviewLog)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.at.desc())
        .limit(limit)
    )
    if since is not None:
        stmt = stmt.where(ReviewLog.at >= since)
    if actions:
        action_list = list(actions)
        if action_list:
            stmt = stmt.where(ReviewLog.action.in_(action_list))
    return list(session.exec(stmt).all())


@dataclass(frozen=True)
class TimelineEntry:
    """One hydrated review-log row ready for the activity timeline UI."""
    log_id: int
    highlight_id: int
    action: str
    at: datetime
    text: str
    note: Optional[str]
    book_id: Optional[int]
    book_title: Optional[str]
    book_author: Optional[str]


def timeline_entries(
    session: Session,
    *,
    user_id: int = 1,
    action: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[TimelineEntry]:
    """Newest-first review-log rows joined with their highlight + book.

    One round-trip — the join replaces the per-row Highlight/Book
    lookups the route would otherwise need. Discarded highlights are
    intentionally **kept** because the log is a record of action,
    including discards; suppressing them would make the timeline lie
    about what happened.
    """
    stmt = (
        select(
            ReviewLog.id,
            ReviewLog.highlight_id,
            ReviewLog.action,
            ReviewLog.at,
            Highlight.text,
            Highlight.note,
            Highlight.book_id,
            Book.title,
            Book.author,
        )
        .join(Highlight, Highlight.id == ReviewLog.highlight_id)
        .outerjoin(Book, Book.id == Highlight.book_id)
        .where(ReviewLog.user_id == user_id)
        .order_by(ReviewLog.at.desc(), ReviewLog.id.desc())
        .offset(offset)
        .limit(limit)
    )
    if action:
        stmt = stmt.where(ReviewLog.action == action)
    rows = session.exec(stmt).all()
    return [
        TimelineEntry(
            log_id=int(r[0]),
            highlight_id=int(r[1]),
            action=str(r[2]),
            at=r[3],
            text=r[4] or "",
            note=r[5],
            book_id=int(r[6]) if r[6] is not None else None,
            book_title=r[7],
            book_author=r[8],
        )
        for r in rows
    ]


def timeline_total(
    session: Session,
    *,
    user_id: int = 1,
    action: Optional[str] = None,
) -> int:
    """Count of review-log rows matching the timeline filters — used by
    the route to render pagination labels without paging through the
    whole log."""
    from sqlalchemy import func as _func
    stmt = (
        select(_func.count(ReviewLog.id))
        .where(ReviewLog.user_id == user_id)
    )
    if action:
        stmt = stmt.where(ReviewLog.action == action)
    return int(session.exec(stmt).one() or 0)


def counts_by_day(
    session: Session,
    *,
    days: int = 7,
    user_id: int = 1,
    today: Optional[date] = None,
) -> list[tuple[date, int]]:
    """Return ``[(day, count), ...]`` for the last ``days`` days, oldest
    first. Days with zero activity get an explicit 0 entry so callers
    can render a sparkline without densifying the gap themselves."""
    end = today or date.today()
    start = end - timedelta(days=days - 1)
    cutoff = datetime.combine(start, datetime.min.time())
    rows = session.exec(
        select(ReviewLog.at)
        .where(ReviewLog.user_id == user_id)
        .where(ReviewLog.at >= cutoff)
    ).all()
    bucket: dict[date, int] = defaultdict(int)
    for at in rows:
        bucket[at.date()] += 1
    return [
        (start + timedelta(days=i), bucket.get(start + timedelta(days=i), 0))
        for i in range(days)
    ]
