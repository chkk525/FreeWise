"""Tests for app.services.echoes + the touch / reread endpoints + progress."""
from __future__ import annotations

from datetime import date, datetime, timedelta, UTC

from sqlmodel import select

from app.models import Highlight
from app.services.echoes import (
    NEGLECT_THRESHOLD_DAYS,
    Echo,
    get_echoes,
)


# ── Source pickers (unit) ───────────────────────────────────────────────


def test_get_echoes_empty_library_returns_empty(db):
    """Fresh install must not crash; just no cards."""
    assert get_echoes(db) == []


def test_anniversary_picks_highlight_from_one_year_ago(db, make_highlight):
    """A highlight created on this date one year ago should surface."""
    today = date(2026, 5, 5)
    last_year = datetime(2025, 5, 5, 12, 0, 0)
    h = make_highlight(text="One year old wisdom")
    h.created_at = last_year
    db.add(h)
    db.commit()
    echoes = get_echoes(db, today=today)
    assert len(echoes) >= 1
    assert any(e.source == "anniversary" and e.years_ago == 1 for e in echoes)


def test_anniversary_handles_feb_29_on_non_leap_target(db, make_highlight):
    """No crash when this year is a leap year and the target year isn't."""
    # Today = Feb 29, target year (one back) = non-leap. The picker
    # falls back to Feb 28 silently.
    today = date(2024, 2, 29)
    h = make_highlight(text="Feb 28 backfill")
    h.created_at = datetime(2023, 2, 28, 12, 0, 0)
    db.add(h)
    db.commit()
    echoes = get_echoes(db, today=today)
    assert any(e.source == "anniversary" for e in echoes)


def test_reread_target_surfaces(db, make_highlight):
    """Highlights flagged 📖 take precedence over neglect."""
    h = make_highlight(text="Reread me")
    h.is_reread_target = True
    db.add(h)
    db.commit()
    echoes = get_echoes(db, limit=3)
    assert any(e.source == "reread" for e in echoes)


def test_neglect_picks_long_unreviewed_book(db, make_highlight):
    """A highlight last reviewed 90 days ago should be classed as neglect."""
    today = date(2026, 5, 5)
    long_ago = datetime.combine(
        today - timedelta(days=90), datetime.min.time()
    )
    h = make_highlight(text="Lonely highlight")
    h.last_reviewed_at = long_ago
    db.add(h)
    db.commit()
    echoes = get_echoes(db, today=today)
    assert any(e.source == "neglect" for e in echoes)


def test_neglect_skips_recently_reviewed(db, make_highlight):
    """A highlight reviewed yesterday must not show as neglect."""
    today = date(2026, 5, 5)
    h = make_highlight(text="Just-reviewed highlight")
    h.last_reviewed_at = datetime.combine(
        today - timedelta(days=1), datetime.min.time()
    )
    db.add(h)
    db.commit()
    # No anniversary (created today by default) and no reread flag, so
    # neglect is the only path that could surface this. It must not.
    echoes = get_echoes(db, today=today)
    assert not any(e.source == "neglect" and e.highlight.id == h.id for e in echoes)


def test_neglect_skips_discarded(db, make_highlight):
    """Discarded highlights never surface (user explicitly removed)."""
    today = date(2026, 5, 5)
    h = make_highlight(text="Tossed")
    h.is_discarded = True
    h.last_reviewed_at = datetime.combine(
        today - timedelta(days=NEGLECT_THRESHOLD_DAYS + 30),
        datetime.min.time(),
    )
    db.add(h)
    db.commit()
    echoes = get_echoes(db, today=today, limit=5)
    assert not any(e.highlight.id == h.id for e in echoes)


def test_get_echoes_respects_limit(db, make_highlight):
    """limit=1 returns at most one card even with multiple sources."""
    h1 = make_highlight(text="1")
    h1.is_reread_target = True
    h2 = make_highlight(text="2")
    h2.is_reread_target = True
    db.add(h1); db.add(h2); db.commit()
    echoes = get_echoes(db, limit=1)
    assert len(echoes) == 1


def test_get_echoes_dedupe_across_sources(db, make_highlight):
    """A highlight that qualifies for two sources only appears once."""
    today = date(2026, 5, 5)
    last_year = datetime(2025, 5, 5, 12, 0, 0)
    h = make_highlight(text="dual-qualifier")
    h.created_at = last_year
    h.is_reread_target = True  # also a reread target
    db.add(h); db.commit()
    echoes = get_echoes(db, today=today, limit=3)
    ids = [e.highlight.id for e in echoes]
    assert len(ids) == len(set(ids))


# ── /touch endpoint ─────────────────────────────────────────────────────


def test_touch_endpoint_bumps_last_reviewed_and_count(client, db, make_highlight):
    h = make_highlight(text="x")
    initial_count = h.review_count or 0
    resp = client.post(f"/highlights/{h.id}/touch")
    assert resp.status_code == 204
    db.expire_all()
    fresh = db.exec(select(Highlight).where(Highlight.id == h.id)).one()
    assert fresh.last_reviewed_at is not None
    assert fresh.review_count == initial_count + 1


def test_touch_endpoint_404_for_missing_highlight(client):
    resp = client.post("/highlights/999999/touch")
    assert resp.status_code == 404


def test_touch_does_not_flip_favorite_or_discard(client, db, make_highlight):
    """Touch must be side-effect-free on user state flags."""
    h = make_highlight(text="x", is_favorited=True)
    client.post(f"/highlights/{h.id}/touch")
    db.expire_all()
    fresh = db.exec(select(Highlight).where(Highlight.id == h.id)).one()
    assert fresh.is_favorited is True
    assert fresh.is_discarded is False
    assert fresh.is_mastered is False


# ── /reread toggle ──────────────────────────────────────────────────────


def test_reread_endpoint_toggles_flag(client, db, make_highlight):
    h = make_highlight(text="x")
    client.post(f"/highlights/{h.id}/reread")
    db.expire_all()
    fresh = db.exec(select(Highlight).where(Highlight.id == h.id)).one()
    assert fresh.is_reread_target is True
    # Toggle off.
    client.post(f"/highlights/{h.id}/reread")
    db.expire_all()
    fresh = db.exec(select(Highlight).where(Highlight.id == h.id)).one()
    assert fresh.is_reread_target is False


# ── Book progress (book_stats) ──────────────────────────────────────────


def test_book_stats_reviewed_count_and_fraction(db, make_book, make_highlight):
    from app.services.book_stats import compute_book_stats
    book = make_book(title="P")
    h1 = make_highlight(text="a", book=book)
    h1.review_count = 1
    h2 = make_highlight(text="b", book=book)  # never reviewed
    db.add(h1); db.add(h2); db.commit()
    stats = compute_book_stats(db, book.id)
    assert stats.reviewed_count == 1
    assert stats.active_count == 2
    assert abs(stats.reviewed_fraction - 0.5) < 1e-6


def test_book_stats_reviewed_zero_for_empty_book(db, make_book):
    from app.services.book_stats import compute_book_stats
    book = make_book(title="empty")
    stats = compute_book_stats(db, book.id)
    assert stats.reviewed_count == 0
    assert stats.reviewed_fraction == 0.0


# ── Echo dataclass identity ─────────────────────────────────────────────


def test_echo_dataclass_is_hashable():
    """Frozen + slots-friendly so it can be a dict key in the future."""
    h = Highlight(text="x", user_id=1)
    e = Echo(source="anniversary", highlight=h, book=None, label="1年前", years_ago=1)
    # Frozen → setattr should fail.
    import dataclasses
    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        e.label = "changed"  # type: ignore[misc]
