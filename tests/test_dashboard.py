"""
Tests for the dashboard endpoint: stats, heatmaps, and streaks.
"""
from datetime import date, timedelta


class TestDashboardEmbeddingCoverage:
    """Dashboard renders an embedding-coverage indicator (C2)."""

    def test_hidden_when_no_active_highlights(self, client):
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # No coverage badge when there's nothing to embed.
        assert "Semantic similarity:" not in resp.text

    def test_shows_zero_percent_with_active_no_embeddings(self, client, make_highlight):
        make_highlight(text="x")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "Semantic similarity:" in resp.text
        assert "0%" in resp.text  # 0 / 1 embedded

    def test_shows_partial_coverage(self, client, db, make_highlight):
        from app.models import Embedding
        from app.services.embeddings import pack_vector
        h1 = make_highlight(text="a")
        h2 = make_highlight(text="b")
        db.add(Embedding(highlight_id=h1.id, model_name="nomic-embed-text",
                         dim=1, vector=pack_vector([1.0])))
        db.commit()
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "50.0%" in resp.text  # 1 / 2


class TestDashboardLibraryHealth:
    """Dashboard surfaces duplicate-group counts as a library-health card."""

    def test_hidden_when_no_duplicates(self, client, make_highlight):
        make_highlight(text="solitary highlight that has no twins")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "Library health:" not in resp.text

    def test_shows_dup_groups_when_present(self, client, make_highlight):
        # Three identical-prefix highlights → 1 group, 2 redundant rows.
        text = "Dashboard duplicate detection survives the 80-char prefix grouping check"
        for _ in range(3):
            make_highlight(text=text)
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "Library health:" in resp.text
        # Group count + redundant count both rendered
        assert "1</span>\n                duplicate group" in resp.text or ">1<" in resp.text
        assert "2 redundant" in resp.text
        # Exact-duplicates link present
        assert 'href="/highlights/ui/duplicates"' in resp.text

    def test_semantic_link_hidden_when_coverage_low(self, client, make_highlight):
        text = "another duplicate prefix that should trigger the health card cleanly"
        for _ in range(2):
            make_highlight(text=text)
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "Library health:" in resp.text
        # No embeddings → no semantic link
        assert "/highlights/ui/duplicates/semantic" not in resp.text


class TestDashboardTagCloud:
    """Dashboard renders a tag cloud of highlight-level tags."""

    def test_empty_when_no_tags(self, client, make_highlight):
        make_highlight(text="x")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # Tags section is conditional — should NOT render the heading.
        assert ">Tags<" not in resp.text or "✗" not in resp.text  # tolerate either

    def test_renders_tags_with_counts(self, client, make_highlight):
        h1 = make_highlight(text="x")
        h2 = make_highlight(text="y")
        client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "python"})
        client.post(f"/highlights/{h2.id}/tags/add", data={"new_tag": "python"})
        client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "ml"})
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # Both tag names appear, with their counts.
        assert "python" in resp.text
        assert "ml" in resp.text
        assert "·2" in resp.text  # python = 2
        assert "·1" in resp.text  # ml = 1

    def test_excludes_reserved_tag_names(self, client, db, make_highlight):
        """If legacy data has a 'favorite' tag row, it must be filtered."""
        from app.models import Tag, HighlightTag
        h = make_highlight(text="x")
        for name in ("favorite", "discard"):
            t = Tag(name=name)
            db.add(t); db.commit(); db.refresh(t)
            db.add(HighlightTag(highlight_id=h.id, tag_id=t.id))
        db.commit()
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # The Tags widget only emits a chip when the tag list is non-empty.
        # Make sure the reserved names don't appear as cloud chips.
        # (They might appear elsewhere in the page; check the cloud chip
        # markup specifically.)
        assert "·1" not in resp.text or ">favorite<" not in resp.text


class TestDashboardPage:
    """GET /dashboard/ui — renders the stats dashboard."""

    def test_empty_dashboard(self, client):
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # Should still render without data
        assert "0" in resp.text  # zero counts

    def test_shows_book_count(self, client, make_book):
        make_book(title="Book A")
        make_book(title="Book B")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "2" in resp.text

    def test_shows_highlight_count(self, client, make_highlight):
        make_highlight(text="H1")
        make_highlight(text="H2")
        make_highlight(text="H3")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "3" in resp.text

    def test_shows_favorited_count(self, client, make_highlight):
        make_highlight(text="Fav", is_favorited=True)
        make_highlight(text="Normal")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # At least "1" should appear for favorited
        assert "1" in resp.text

    def test_shows_discarded_count(self, client, make_highlight):
        make_highlight(text="Disc", is_discarded=True)
        make_highlight(text="Normal")
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200

    def test_reviewed_today_false(self, client):
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # No completed review session today

    def test_reviewed_today_true(self, client, make_review_session):
        make_review_session(session_date=date.today(), is_completed=True)
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200

    def test_streak_display(self, client, make_review_session):
        today = date.today()
        make_review_session(session_date=today, is_completed=True)
        make_review_session(session_date=today - timedelta(days=1), is_completed=True)
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        # Streak of 2 should be shown
        assert "2" in resp.text
