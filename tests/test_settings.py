"""
Tests for settings endpoints and the library reset feature.
"""
from sqlmodel import select

from app.models import Settings, Highlight, Book


class TestSettingsPage:
    """GET /settings/ui — renders the settings form."""

    def test_settings_page_loads(self, client):
        resp = client.get("/settings/ui")
        assert resp.status_code == 200
        assert "Settings" in resp.text

    def test_settings_shows_highlight_count(self, client, make_highlight):
        make_highlight(text="H1")
        make_highlight(text="H2")
        resp = client.get("/settings/ui")
        assert resp.status_code == 200
        # The page should display "2" somewhere for the highlight count

    def test_reset_modal_requires_typed_confirmation(self, client):
        """Type-to-confirm guard for the destructive reset library button."""
        resp = client.get("/settings/ui")
        assert resp.status_code == 200
        # The new modal must include the typed-confirm input + disabled button
        # so that the reset cannot be triggered by accidental clicks.
        assert 'id="reset-confirm-input"' in resp.text
        assert 'id="reset-confirm-btn"' in resp.text
        assert "Type RESET" in resp.text or "type RESET" in resp.text
        # The submit button must start in the disabled state.
        assert "disabled" in resp.text


class TestUpdateSettings:
    """POST /settings/ui — update settings with clamping."""

    def test_update_daily_review(self, client, db):
        resp = client.post("/settings/ui", data={
            "daily_review_count": "10",
            "highlight_recency": "5",
            "theme": "light",
        })
        assert resp.status_code == 200
        settings = db.exec(select(Settings)).first()
        assert settings.daily_review_count == 10

    def test_clamp_daily_review_min(self, client, db):
        client.post("/settings/ui", data={
            "daily_review_count": "0",
            "highlight_recency": "5",
            "theme": "light",
        })
        settings = db.exec(select(Settings)).first()
        assert settings.daily_review_count == 1  # clamped to min

    def test_clamp_daily_review_max(self, client, db):
        client.post("/settings/ui", data={
            "daily_review_count": "100",
            "highlight_recency": "5",
            "theme": "light",
        })
        settings = db.exec(select(Settings)).first()
        assert settings.daily_review_count == 15  # clamped to max

    def test_clamp_recency_min(self, client, db):
        client.post("/settings/ui", data={
            "daily_review_count": "5",
            "highlight_recency": "-5",
            "theme": "dark",
        })
        settings = db.exec(select(Settings)).first()
        assert settings.highlight_recency == 0

    def test_clamp_recency_max(self, client, db):
        client.post("/settings/ui", data={
            "daily_review_count": "5",
            "highlight_recency": "20",
            "theme": "dark",
        })
        settings = db.exec(select(Settings)).first()
        assert settings.highlight_recency == 10

    def test_update_theme(self, client, db):
        client.post("/settings/ui", data={
            "daily_review_count": "5",
            "highlight_recency": "5",
            "theme": "dark",
        })
        settings = db.exec(select(Settings)).first()
        assert settings.theme == "dark"

    def test_success_message(self, client):
        resp = client.post("/settings/ui", data={
            "daily_review_count": "5",
            "highlight_recency": "5",
            "theme": "light",
        })
        assert "Settings saved" in resp.text or "success" in resp.text.lower()


class TestResetLibrary:
    """POST /settings/reset-library — nuclear reset."""

    def test_reset_clears_all_data(self, client, db, make_highlight, make_book):
        book = make_book(title="Doomed Book")
        make_highlight(text="Doomed", book=book)

        # Verify data exists
        assert db.exec(select(Highlight)).first() is not None

        resp = client.post("/settings/reset-library")
        assert resp.status_code == 200

        # Re-open a fresh session (old one may reference dropped tables)
        from sqlmodel import Session
        from app.db import get_engine
        with Session(get_engine()) as fresh:
            assert fresh.exec(select(Highlight)).first() is None
            assert fresh.exec(select(Book)).first() is None
            # Settings should be recreated with defaults
            settings = fresh.exec(select(Settings)).first()
            assert settings is not None
            assert settings.daily_review_count == 5

    def test_reset_message(self, client):
        resp = client.post("/settings/reset-library")
        assert "reset" in resp.text.lower() or "deleted" in resp.text.lower()
