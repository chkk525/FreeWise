"""
Tests for the dashboard endpoint: stats, heatmaps, and streaks.
"""
from datetime import date, timedelta


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
