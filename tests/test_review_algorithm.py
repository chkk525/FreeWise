"""
Tests for the review algorithm (scoring, selection, diversity, recency bias).

Uses the real production endpoint GET /highlights/review/ via the TestClient
so the algorithm is tested end-to-end against a real database.
"""
import math
from datetime import datetime, timedelta
from collections import Counter

from sqlmodel import select

from app.models import Highlight, Settings


class TestTimeDecay:
    """Time-decay scoring: score = 1 - exp(-days / 14)."""

    def test_just_reviewed_excluded(self, client, db, make_highlight):
        """A highlight reviewed moments ago should have score≈0 and be skipped
        when other candidates exist."""
        make_highlight(text="Old", created_at=datetime(2024, 1, 1))
        make_highlight(text="Fresh", last_reviewed_at=datetime.utcnow())

        resp = client.get("/highlights/review/", params={"n": 1})
        assert resp.status_code == 200
        ids = [h["id"] for h in resp.json()]
        # The fresh one should almost never win
        fresh = db.exec(
            select(Highlight).where(Highlight.text == "Fresh")
        ).first()
        # In a single draw the old one should dominate (probabilistic, but with
        # enormous score difference it's effectively deterministic)
        if len(ids) == 1:
            assert ids[0] != fresh.id

    def test_older_highlights_score_higher(self, client, db, make_highlight):
        """Highlights not reviewed for a long time should dominate selection."""
        make_highlight(
            text="Ancient",
            created_at=datetime(2023, 1, 1),
            last_reviewed_at=datetime(2023, 6, 1),
        )
        make_highlight(
            text="Recent",
            created_at=datetime(2025, 12, 1),
            last_reviewed_at=datetime.utcnow() - timedelta(hours=1),
        )
        # Run 30 draws and count
        counts = Counter()
        for _ in range(30):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                counts[h["text"]] += 1
        assert counts["Ancient"] > counts["Recent"]


class TestWeightSystem:
    """highlight_weight and book.review_weight affect scoring."""

    def test_zero_highlight_weight_excluded(self, client, db, make_highlight):
        make_highlight(text="Excluded", highlight_weight=0.0)
        make_highlight(text="Included", highlight_weight=1.0)
        resp = client.get("/highlights/review/", params={"n": 1})
        items = resp.json()
        assert all(h["text"] != "Excluded" for h in items)

    def test_zero_book_weight_excluded(self, client, db, make_book, make_highlight):
        from app.models import Book
        b_never = make_book(title="Never", review_weight=0.0)
        b_normal = make_book(title="Normal", review_weight=1.0)
        make_highlight(text="From Never", book=b_never)
        make_highlight(text="From Normal", book=b_normal)

        resp = client.get("/highlights/review/", params={"n": 1})
        items = resp.json()
        assert all(h["text"] != "From Never" for h in items)

    def test_higher_weight_dominates(self, client, db, make_book, make_highlight):
        """hw=2.0 should appear much more often than hw=0.25 over many draws."""
        b = make_book(title="Same Book")
        make_highlight(text="Heavy", book=b, highlight_weight=2.0,
                       created_at=datetime(2024, 6, 1))
        make_highlight(text="Light", book=b, highlight_weight=0.25,
                       created_at=datetime(2024, 6, 1))
        counts = Counter()
        for _ in range(60):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                counts[h["text"]] += 1
        assert counts["Heavy"] > counts["Light"]


class TestDiscardedExclusion:
    """Discarded highlights must never appear in review."""

    def test_discarded_excluded(self, client, db, make_highlight):
        make_highlight(text="Active", is_discarded=False)
        make_highlight(text="Discarded", is_discarded=True)
        for _ in range(10):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                assert h["text"] != "Discarded"

    def test_all_discarded_returns_empty(self, client, db, make_highlight):
        make_highlight(text="D1", is_discarded=True)
        make_highlight(text="D2", is_discarded=True)
        resp = client.get("/highlights/review/", params={"n": 5})
        assert resp.json() == []


class TestDiversity:
    """Per-book cap ensures variety in review selection."""

    def test_no_duplicates(self, client, db, make_book, make_highlight):
        """Each highlight should appear at most once per review."""
        b = make_book(title="One Book")
        for i in range(10):
            make_highlight(text=f"HL {i}", book=b,
                           created_at=datetime(2024, 1, 1))
        resp = client.get("/highlights/review/", params={"n": 5})
        ids = [h["id"] for h in resp.json()]
        assert len(ids) == len(set(ids))

    def test_per_book_cap_respected(self, client, db, make_book, make_highlight):
        """With n≥4, max 2 highlights per book when enough books exist."""
        books = [make_book(title=f"Book {i}") for i in range(5)]
        for b in books:
            for j in range(5):
                make_highlight(text=f"{b.title} HL {j}", book=b,
                               created_at=datetime(2024, 1, 1))

        for _ in range(20):
            resp = client.get("/highlights/review/", params={"n": 5})
            items = resp.json()
            book_counts = Counter(h["book_id"] for h in items)
            for count in book_counts.values():
                assert count <= 2

    def test_fill_from_single_book(self, client, db, make_book, make_highlight):
        """If only one book exists, should still fill up to n."""
        b = make_book(title="Only Book")
        for i in range(10):
            make_highlight(text=f"HL {i}", book=b,
                           created_at=datetime(2024, 1, 1))
        resp = client.get("/highlights/review/", params={"n": 5})
        assert len(resp.json()) == 5


class TestEmptyPool:
    """Edge cases when the highlight pool is empty or tiny."""

    def test_no_highlights_returns_empty(self, client):
        resp = client.get("/highlights/review/", params={"n": 5})
        assert resp.json() == []

    def test_fewer_than_n(self, client, db, make_highlight):
        make_highlight(text="Only one", created_at=datetime(2024, 1, 1))
        resp = client.get("/highlights/review/", params={"n": 5})
        items = resp.json()
        assert len(items) == 1


class TestRecencyBias:
    """highlight_recency setting shifts preference toward older/newer."""

    def _set_recency(self, db, value: int):
        settings = db.exec(select(Settings)).first()
        settings.highlight_recency = value
        db.add(settings)
        db.commit()

    def test_prefer_older(self, client, db, make_highlight):
        """recency=0 should strongly prefer older highlights."""
        self._set_recency(db, 0)
        make_highlight(text="Old", created_at=datetime(2023, 1, 1))
        make_highlight(text="New", created_at=datetime.utcnow() - timedelta(days=2))

        counts = Counter()
        for _ in range(50):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                counts[h["text"]] += 1
        assert counts["Old"] > counts["New"]

    def test_prefer_newer(self, client, db, make_highlight):
        """recency=10 should strongly prefer newer highlights."""
        self._set_recency(db, 10)
        make_highlight(text="Old", created_at=datetime(2023, 1, 1))
        make_highlight(text="New", created_at=datetime.utcnow() - timedelta(days=2))

        counts = Counter()
        for _ in range(50):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                counts[h["text"]] += 1
        assert counts["New"] > counts["Old"]

    def test_neutral_no_bias(self, client, db, make_highlight):
        """recency=5 (neutral) should have no recency bias effect."""
        self._set_recency(db, 5)
        # Two highlights created at identical age, so scores should be equal
        dt = datetime(2024, 6, 1)
        make_highlight(text="A", created_at=dt)
        make_highlight(text="B", created_at=dt)

        counts = Counter()
        for _ in range(100):
            resp = client.get("/highlights/review/", params={"n": 1})
            for h in resp.json():
                counts[h["text"]] += 1
        # With no bias and equal conditions, should be roughly 50/50
        total = counts["A"] + counts["B"]
        assert 0.2 < counts["A"] / total < 0.8
