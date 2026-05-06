"""Tests for /digest/today (the deterministic-per-day web digest)."""
from __future__ import annotations

from datetime import date

from app.services.digest import today_picks


def test_today_picks_returns_empty_when_no_highlights(db):
    assert today_picks(db, count=10) == []


def test_today_picks_is_deterministic_for_same_date(db, make_book, make_highlight):
    b = make_book(title="b")
    for i in range(40):
        make_highlight(text=f"h{i}", book=b)

    a = today_picks(db, count=10, today=date(2026, 5, 4))
    b2 = today_picks(db, count=10, today=date(2026, 5, 4))
    assert [h.id for h in a] == [h.id for h in b2]
    assert len(a) == 10


def test_today_picks_changes_when_date_changes(db, make_book, make_highlight):
    b = make_book(title="b")
    for i in range(40):
        make_highlight(text=f"h{i}", book=b)

    today = today_picks(db, count=10, today=date(2026, 5, 4))
    tomorrow = today_picks(db, count=10, today=date(2026, 5, 5))
    assert [h.id for h in today] != [h.id for h in tomorrow]


def test_today_picks_excludes_discarded(db, make_book, make_highlight):
    b = make_book(title="b")
    for i in range(20):
        make_highlight(text=f"keep{i}", book=b)
    for i in range(5):
        make_highlight(text=f"drop{i}", book=b, is_discarded=True)
    rows = today_picks(db, count=25, today=date(2026, 5, 4))
    # 20 active rows; even with count=25 we can only get 20 distinct picks.
    assert len(rows) == 20
    assert all(not h.is_discarded for h in rows)


def test_today_picks_caps_at_active_pool_size(db, make_book, make_highlight):
    b = make_book(title="b")
    for i in range(3):
        make_highlight(text=f"h{i}", book=b)
    rows = today_picks(db, count=10)
    assert len(rows) == 3
    # Distinct ids — sample without replacement.
    assert len({h.id for h in rows}) == 3


def test_today_picks_distinct_ids(db, make_book, make_highlight):
    """Even with a small pool and a count near pool size, no duplicates."""
    b = make_book(title="b")
    for i in range(15):
        make_highlight(text=f"h{i}", book=b)
    rows = today_picks(db, count=15, today=date(2026, 6, 1))
    assert len(rows) == 15
    assert len({h.id for h in rows}) == 15


def test_digest_today_route_renders(client, make_book, make_highlight):
    b = make_book(title="Discourses", author="Epictetus")
    for i in range(12):
        make_highlight(text=f"insight {i}", book=b)
    resp = client.get("/digest/today")
    assert resp.status_code == 200, resp.text
    assert "Today's Digest" in resp.text
    # The 10-pick section title.
    assert "Today's sample" in resp.text
    # At least one of our seeded book attributions shows up.
    assert "Epictetus" in resp.text or "Discourses" in resp.text


def test_digest_today_route_sets_cache_header(client, make_book, make_highlight):
    b = make_book(title="b")
    make_highlight(text="x", book=b)
    resp = client.get("/digest/today")
    assert resp.status_code == 200
    cc = resp.headers.get("cache-control", "")
    assert "max-age=" in cc
    assert "private" in cc


def test_digest_today_empty_library_renders_empty_state(client):
    resp = client.get("/digest/today")
    assert resp.status_code == 200
    assert "import" in resp.text.lower()
