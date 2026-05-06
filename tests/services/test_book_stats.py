"""Tests for app.services.book_stats.compute_book_stats."""
from __future__ import annotations

from datetime import datetime

from sqlmodel import select

from app.models import Highlight, HighlightTag, Tag
from app.services.book_stats import BookStats, compute_book_stats


def test_empty_book_returns_zero_stats(db, make_book):
    book = make_book(title="Empty")
    stats = compute_book_stats(db, book.id)
    assert stats == BookStats()
    assert stats.mastered_fraction == 0.0
    assert stats.total_count == 0


def test_counts_split_active_discarded_favorited_mastered(db, make_book, make_highlight):
    b = make_book(title="Counts")
    make_highlight(text="a", book=b)
    make_highlight(text="b", book=b, is_favorited=True)
    h = make_highlight(text="c", book=b)
    h.is_mastered = True
    db.add(h)
    db.commit()
    make_highlight(text="d", book=b, is_discarded=True)

    stats = compute_book_stats(db, b.id)
    assert stats.active_count == 3
    assert stats.discarded_count == 1
    assert stats.favorited_count == 1
    assert stats.mastered_count == 1
    assert stats.total_count == 4
    assert abs(stats.mastered_fraction - 1 / 3) < 1e-6


def test_avg_highlight_length_rounds_to_int(db, make_book, make_highlight):
    b = make_book(title="Lengths")
    make_highlight(text="x" * 10, book=b)
    make_highlight(text="y" * 22, book=b)
    stats = compute_book_stats(db, b.id)
    assert stats.avg_highlight_length == 16  # (10 + 22) / 2


def test_date_range_uses_min_max_created_at(db, make_book, make_highlight):
    b = make_book(title="Dates")
    make_highlight(text="early", book=b, created_at=datetime(2024, 1, 1))
    make_highlight(text="middle", book=b, created_at=datetime(2025, 6, 15))
    make_highlight(text="late", book=b, created_at=datetime(2026, 3, 30))
    stats = compute_book_stats(db, b.id)
    assert stats.earliest_highlight_at == datetime(2024, 1, 1)
    assert stats.latest_highlight_at == datetime(2026, 3, 30)


def test_last_reviewed_and_total_reviews_aggregate(db, make_book, make_highlight):
    b = make_book(title="Reviewed")
    make_highlight(
        text="a", book=b,
        last_reviewed_at=datetime(2026, 1, 1),
        review_count=3,
    )
    make_highlight(
        text="b", book=b,
        last_reviewed_at=datetime(2026, 4, 12),
        review_count=2,
    )
    stats = compute_book_stats(db, b.id)
    assert stats.last_reviewed_at == datetime(2026, 4, 12)
    assert stats.total_review_count == 5


def test_top_tags_returns_top_three_only_for_active_highlights(db, make_book, make_highlight):
    b = make_book(title="Tagged")
    h1 = make_highlight(text="1", book=b)
    h2 = make_highlight(text="2", book=b)
    h3 = make_highlight(text="3", book=b)
    h_disc = make_highlight(text="x", book=b, is_discarded=True)

    # Tags
    t_phil = Tag(name="philosophy")
    t_hist = Tag(name="history")
    t_econ = Tag(name="economics")
    t_misc = Tag(name="misc")
    db.add(t_phil); db.add(t_hist); db.add(t_econ); db.add(t_misc)
    db.commit()
    for tag in (t_phil, t_hist, t_econ, t_misc):
        db.refresh(tag)

    # Wire highlight ↔ tag links
    db.add(HighlightTag(highlight_id=h1.id, tag_id=t_phil.id))
    db.add(HighlightTag(highlight_id=h2.id, tag_id=t_phil.id))
    db.add(HighlightTag(highlight_id=h3.id, tag_id=t_phil.id))
    db.add(HighlightTag(highlight_id=h1.id, tag_id=t_hist.id))
    db.add(HighlightTag(highlight_id=h2.id, tag_id=t_hist.id))
    db.add(HighlightTag(highlight_id=h1.id, tag_id=t_econ.id))
    # `misc` only appears on a discarded highlight — must be excluded.
    db.add(HighlightTag(highlight_id=h_disc.id, tag_id=t_misc.id))
    db.commit()

    stats = compute_book_stats(db, b.id)
    assert stats.top_tags == [
        ("philosophy", 3),
        ("history", 2),
        ("economics", 1),
    ]
    # `misc` was tagged on a discarded highlight, not in the top list.
    assert all(name != "misc" for name, _ in stats.top_tags)


def test_stats_panel_renders_in_book_detail_html(client, make_book, make_highlight):
    b = make_book(title="Insights Render")
    make_highlight(text="lorem ipsum dolor", book=b, created_at=datetime(2026, 2, 1))
    make_highlight(
        text="another insight", book=b,
        created_at=datetime(2026, 4, 1),
        last_reviewed_at=datetime(2026, 5, 1),
        review_count=2,
    )
    resp = client.get(f"/library/ui/book/{b.id}")
    assert resp.status_code == 200, resp.text
    assert "Insights" in resp.text
    assert "Avg length" in resp.text
    assert "2026-02-01" in resp.text
    assert "2026-04-01" in resp.text
    assert "Last reviewed" in resp.text
    assert "2026-05-01" in resp.text
    assert "Total reviews" in resp.text


def test_stats_panel_omitted_when_book_has_no_highlights(client, make_book):
    b = make_book(title="Empty Book")
    resp = client.get(f"/library/ui/book/{b.id}")
    assert resp.status_code == 200
    # Insights panel does not render when there are no highlights.
    assert "Insights" not in resp.text or "id=\"book-stats\"" not in resp.text
