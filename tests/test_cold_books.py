"""Tests for the dashboard cold-books re-engagement widget.

Covers ``app.services.cold_books.cold_books`` and the dashboard render
that surfaces it. Concretely:

  * Books that have **never** been touched sort ahead of touched books.
  * ``ReviewLog.at`` takes precedence when newer than
    ``Highlight.last_reviewed_at`` (and vice-versa when older).
  * Books whose only highlights are discarded are excluded — we don't
    nag the user about garbage they already swept out.
  * The dashboard HTML actually renders the widget when entries exist.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.models import ReviewLog
from app.services.cold_books import cold_books


# ── Service unit tests ────────────────────────────────────────────────────


def test_never_touched_sorts_before_touched(db, make_highlight, make_book):
    """A pristine import outranks anything with any review history."""
    pristine = make_book(title="Pristine")
    touched = make_book(title="Touched")
    make_highlight(book=pristine, last_reviewed_at=None)
    make_highlight(book=touched, last_reviewed_at=datetime(2025, 1, 1))

    out = cold_books(db, limit=5)
    titles = [e.title for e in out]
    assert titles.index("Pristine") < titles.index("Touched")
    pristine_entry = next(e for e in out if e.title == "Pristine")
    touched_entry = next(e for e in out if e.title == "Touched")
    assert pristine_entry.last_touched_at is None
    assert touched_entry.last_touched_at == datetime(2025, 1, 1)


def test_oldest_touched_sorts_before_newest(db, make_highlight, make_book):
    stale = make_book(title="Stale")
    fresh = make_book(title="Fresh")
    make_highlight(book=stale, last_reviewed_at=datetime(2024, 1, 1))
    make_highlight(book=fresh, last_reviewed_at=datetime(2026, 1, 1))

    out = cold_books(db, limit=5)
    titles = [e.title for e in out]
    assert titles.index("Stale") < titles.index("Fresh")


def test_review_log_takes_precedence_over_old_last_reviewed_at(
    db, make_highlight, make_book
):
    """A fresh ReviewLog entry should mark the book as touched recently
    even if the highlight's pre-log ``last_reviewed_at`` is ancient."""
    revived = make_book(title="Revived")
    h_revived = make_highlight(book=revived, last_reviewed_at=datetime(2024, 1, 1))
    db.add(
        ReviewLog(
            highlight_id=h_revived.id,
            user_id=1,
            action="favorite",
            at=datetime(2026, 4, 1),
        )
    )

    untouched = make_book(title="Untouched")
    make_highlight(book=untouched, last_reviewed_at=datetime(2025, 1, 1))
    db.commit()

    out = cold_books(db, limit=5)
    titles = [e.title for e in out]
    # Revived should now sort *after* Untouched even though its
    # last_reviewed_at column is older — the ReviewLog row dominates.
    assert titles.index("Untouched") < titles.index("Revived")


def test_last_reviewed_at_used_when_newer_than_review_log(
    db, make_highlight, make_book
):
    """The reverse case: a highlight bumped via the legacy review flow
    keeps that recency even when an old ReviewLog row exists."""
    book = make_book(title="MixedSignal")
    h = make_highlight(book=book, last_reviewed_at=datetime(2026, 4, 1))
    db.add(
        ReviewLog(
            highlight_id=h.id,
            user_id=1,
            action="favorite",
            at=datetime(2024, 1, 1),
        )
    )
    db.commit()

    out = cold_books(db, limit=5)
    entry = next(e for e in out if e.title == "MixedSignal")
    assert entry.last_touched_at == datetime(2026, 4, 1)


def test_book_with_only_discarded_highlights_is_excluded(
    db, make_highlight, make_book
):
    swept = make_book(title="SweptOut")
    make_highlight(book=swept, is_discarded=True)
    keep = make_book(title="Keeper")
    make_highlight(book=keep)

    titles = [e.title for e in cold_books(db, limit=5)]
    assert "Keeper" in titles
    assert "SweptOut" not in titles


def test_active_highlight_count_excludes_discarded(
    db, make_highlight, make_book
):
    book = make_book(title="HalfDiscarded")
    make_highlight(book=book, text="keep me")
    make_highlight(book=book, text="keep me too")
    make_highlight(book=book, text="discarded", is_discarded=True)

    out = cold_books(db, limit=5)
    entry = next(e for e in out if e.title == "HalfDiscarded")
    assert entry.active_highlights == 2


def test_limit_argument_caps_returned_rows(db, make_highlight, make_book):
    for i in range(7):
        b = make_book(title=f"Book{i}")
        make_highlight(book=b, last_reviewed_at=datetime(2025, 1, 1) + timedelta(days=i))

    out = cold_books(db, limit=3)
    assert len(out) == 3


def test_other_user_books_excluded(db, make_highlight, make_book):
    """Cold-books is per-user — book 1 (other user) shouldn't surface
    when the dashboard asks for user_id=1's data."""
    mine = make_book(title="Mine")
    theirs = make_book(title="Theirs")
    make_highlight(book=mine, user_id=1)
    make_highlight(book=theirs, user_id=99)

    titles = [e.title for e in cold_books(db, limit=5, user_id=1)]
    assert "Mine" in titles
    assert "Theirs" not in titles


# ── Dashboard render ─────────────────────────────────────────────────────


def test_dashboard_renders_cold_books_widget(client, make_highlight, make_book):
    """When there's at least one active book, the widget should render
    the heading and link to the book detail page."""
    b = make_book(title="LongTailBook", author="Forgotten Sage")
    make_highlight(book=b)

    resp = client.get("/dashboard/ui")
    assert resp.status_code == 200
    body = resp.text
    # Heading text from the new widget block.
    assert "Books going cold" in body
    # Book row links into the library.
    assert f'/library/ui/book/{b.id}' in body
    assert "LongTailBook" in body
    assert "Forgotten Sage" in body


def test_dashboard_widget_marks_never_reviewed(client, make_highlight, make_book):
    b = make_book(title="UntouchedBook")
    make_highlight(book=b, last_reviewed_at=None)

    resp = client.get("/dashboard/ui")
    assert resp.status_code == 200
    assert "never reviewed" in resp.text


def test_dashboard_widget_hidden_when_empty(client):
    """No active highlights → widget block isn't emitted at all."""
    resp = client.get("/dashboard/ui")
    assert resp.status_code == 200
    assert "Books going cold" not in resp.text
