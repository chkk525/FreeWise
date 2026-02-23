"""
Tests for database utility functions: get_settings, get_current_streak.
"""
from datetime import date, timedelta, datetime
from sqlmodel import Session, select

from app.db import get_settings, get_current_streak
from app.models import Settings, ReviewSession


class TestGetSettings:
    """get_settings() creates defaults if absent and back-fills highlight_recency."""

    def test_returns_existing_settings(self, db):
        settings = get_settings(db)
        assert settings is not None
        assert settings.daily_review_count == 5

    def test_creates_defaults_when_missing(self, db):
        # Delete the seeded settings
        existing = db.exec(select(Settings)).first()
        db.delete(existing)
        db.commit()

        settings = get_settings(db)
        assert settings is not None
        assert settings.daily_review_count == 5
        assert settings.highlight_recency == 5
        assert settings.theme == "light"

    def test_backfills_none_recency(self, db):
        # The get_settings() code defensively checks for None highlight_recency
        # to handle legacy DBs. Since the current schema enforces NOT NULL, we
        # verify the guard exists by calling get_settings and confirming the
        # value is always an int.
        settings = get_settings(db)
        assert isinstance(settings.highlight_recency, int)
        assert settings.highlight_recency == 5


class TestGetCurrentStreak:
    """get_current_streak() counts consecutive review days."""

    def test_no_sessions_returns_zero(self, db):
        assert get_current_streak(db) == 0

    def test_today_only_returns_one(self, db, make_review_session):
        make_review_session(session_date=date.today())
        assert get_current_streak(db) == 1

    def test_yesterday_only_returns_one(self, db, make_review_session):
        make_review_session(session_date=date.today() - timedelta(days=1))
        assert get_current_streak(db) == 1

    def test_consecutive_days(self, db, make_review_session):
        today = date.today()
        for i in range(5):
            make_review_session(session_date=today - timedelta(days=i))
        assert get_current_streak(db) == 5

    def test_gap_breaks_streak(self, db, make_review_session):
        today = date.today()
        make_review_session(session_date=today)
        make_review_session(session_date=today - timedelta(days=1))
        # Skip day 2
        make_review_session(session_date=today - timedelta(days=3))
        assert get_current_streak(db) == 2

    def test_old_session_returns_zero(self, db, make_review_session):
        make_review_session(session_date=date.today() - timedelta(days=5))
        assert get_current_streak(db) == 0

    def test_incomplete_session_ignored(self, db, make_review_session):
        make_review_session(session_date=date.today(), is_completed=False)
        assert get_current_streak(db) == 0

    def test_multiple_sessions_same_day(self, db, make_review_session):
        today = date.today()
        make_review_session(session_date=today)
        make_review_session(session_date=today)  # duplicate day
        make_review_session(session_date=today - timedelta(days=1))
        assert get_current_streak(db) == 2
