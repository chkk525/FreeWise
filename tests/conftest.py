"""
Shared pytest fixtures for the FreeWise test suite.

Provides an isolated in-memory SQLite database, a seeded FastAPI TestClient,
and convenience factories for creating test data.
"""
import sys
from pathlib import Path
from datetime import datetime, date, timedelta, UTC

import pytest
from fastapi.testclient import TestClient
from sqlmodel import create_engine, Session, SQLModel, select
from sqlalchemy.pool import StaticPool

# ── Make app importable ───────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Build the test engine BEFORE importing the app ────────────────────────────
_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

# Patch app.db._engine so get_engine() and get_session() both use test DB
import app.db as _db
_db._engine = _test_engine

# Now import the app (model registration happens at import time)
from app.main import app  # noqa: E402
from app.models import User, Book, Highlight, Settings, Tag, HighlightTag, ReviewSession, Embedding  # noqa: E402,F401


def _override_get_session():
    """Dependency override that yields sessions from the test engine."""
    with Session(_test_engine) as session:
        yield session


app.dependency_overrides[_db.get_session] = _override_get_session


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_db():
    """Drop and recreate all tables before every test for full isolation."""
    SQLModel.metadata.drop_all(_test_engine)
    SQLModel.metadata.create_all(_test_engine)

    # Apply forward-only migrations (FTS5 virtual table + triggers, etc.).
    # The lifespan hook normally does this on app startup; with TestClient
    # we have to call it ourselves so search/* tests have a working index.
    from app.db import ensure_schema_migrations
    ensure_schema_migrations(_test_engine)

    # Seed minimal required data
    with Session(_test_engine) as s:
        s.add(User(id=1, email="test@test.com", password_hash="x"))
        s.add(Settings(daily_review_count=5, highlight_recency=5, theme="light"))
        s.commit()

    # Clear in-process state shared across tests so they don't bleed:
    #  - rate limit bucket (else /api/v2/* tests after the rate-limit test
    #    inherit a saturated bucket and start failing with 429)
    #  - last_used_at debounce cache
    #  - review_sessions in-memory dict
    try:
        from app.main import _RATE_LIMIT_BUCKET
        _RATE_LIMIT_BUCKET.clear()
    except Exception:
        pass
    try:
        from app.api_v2.auth import _last_used_at_cache
        _last_used_at_cache.clear()
    except Exception:
        pass

    yield  # test runs here

    # Clean up in-memory review sessions between tests
    from app.routers.highlights import review_sessions
    review_sessions.clear()


@pytest.fixture()
def db():
    """Yield a raw SQLModel Session bound to the test engine."""
    with Session(_test_engine) as session:
        yield session


@pytest.fixture()
def client():
    """Yield a FastAPI TestClient with the lifespan context active."""
    with TestClient(app) as c:
        yield c


# ── Factory helpers ───────────────────────────────────────────────────────────

@pytest.fixture()
def make_book(db):
    """Factory fixture: create a Book and return it."""

    def _make(title="Test Book", author="Test Author", review_weight=1.0, **kw):
        book = Book(title=title, author=author, review_weight=review_weight, **kw)
        db.add(book)
        db.commit()
        db.refresh(book)
        return book

    return _make


@pytest.fixture()
def make_highlight(db, make_book):
    """Factory fixture: create a Highlight (auto-creates a book if needed)."""

    _default_book = None

    def _make(
        text="A test highlight",
        book=None,
        book_id=None,
        user_id=1,
        highlight_weight=1.0,
        is_favorited=False,
        is_discarded=False,
        created_at=None,
        last_reviewed_at=None,
        review_count=0,
        note=None,
        location=None,
        location_type=None,
        **kw,
    ):
        nonlocal _default_book
        if book is None and book_id is None:
            if _default_book is None:
                _default_book = make_book()
            book_id = _default_book.id
        elif book is not None:
            book_id = book.id

        h = Highlight(
            text=text,
            book_id=book_id,
            user_id=user_id,
            highlight_weight=highlight_weight,
            is_favorited=is_favorited,
            is_discarded=is_discarded,
            created_at=created_at or datetime(2025, 6, 1),
            last_reviewed_at=last_reviewed_at,
            review_count=review_count,
            note=note,
            location=location,
            location_type=location_type,
            **kw,
        )
        db.add(h)
        db.commit()
        db.refresh(h)
        return h

    return _make


@pytest.fixture()
def make_review_session(db):
    """Factory fixture: create a ReviewSession record."""

    def _make(
        session_uuid=None,
        user_id=1,
        started_at=None,
        completed_at=None,
        session_date=None,
        target_count=5,
        highlights_reviewed=5,
        highlights_discarded=0,
        highlights_favorited=0,
        is_completed=True,
    ):
        import uuid as _uuid
        now = datetime.now(UTC).replace(tzinfo=None)
        rs = ReviewSession(
            user_id=user_id,
            session_uuid=session_uuid or str(_uuid.uuid4()),
            started_at=started_at or now,
            completed_at=completed_at or now,
            session_date=session_date or date.today(),
            target_count=target_count,
            highlights_reviewed=highlights_reviewed,
            highlights_discarded=highlights_discarded,
            highlights_favorited=highlights_favorited,
            is_completed=is_completed,
        )
        db.add(rs)
        db.commit()
        db.refresh(rs)
        return rs

    return _make
