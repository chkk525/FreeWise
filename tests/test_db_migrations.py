"""Tests for app.db.ensure_schema_migrations.

Verifies the lightweight ALTER TABLE / backfill helper used in lifespan to
upgrade pre-Phase-3 SQLite databases in place.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from app.db import ensure_schema_migrations
from app.models import Book


def _fresh_engine():
    return create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _columns(engine, table: str) -> set[str]:
    with engine.connect() as conn:
        return {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})")).all()}


def test_migration_adds_kindle_asin_column_to_pre_existing_table() -> None:
    """Simulate a DB created before kindle_asin existed in the model."""
    engine = _fresh_engine()
    with engine.begin() as conn:
        # Hand-roll the pre-Phase-3 schema: book WITHOUT kindle_asin.
        conn.execute(
            text(
                "CREATE TABLE book ("
                "id INTEGER PRIMARY KEY, "
                "title VARCHAR, "
                "author VARCHAR, "
                "document_tags VARCHAR, "
                "review_weight FLOAT, "
                "cover_image_url VARCHAR, "
                "cover_image_source VARCHAR"
                ")"
            )
        )
        conn.execute(
            text(
                "INSERT INTO book (id, title, author, document_tags) VALUES "
                "(1, 'Sapiens', 'Y', 'asin:B07FCMBLM6,history'), "
                "(2, 'No Tag', 'X', NULL), "
                "(3, 'Tag No ASIN', NULL, 'history,readlater')"
            )
        )

    assert "kindle_asin" not in _columns(engine, "book")
    ensure_schema_migrations(engine)
    assert "kindle_asin" in _columns(engine, "book")

    # Backfill: row 1 had asin tag → kindle_asin=B07FCMBLM6
    with engine.connect() as conn:
        rows = conn.execute(
            text("SELECT id, kindle_asin FROM book ORDER BY id")
        ).all()
        assert rows == [(1, "B07FCMBLM6"), (2, None), (3, None)]


def test_migration_idempotent_on_already_migrated_db() -> None:
    """Running twice — and on a fresh model-built schema — is a no-op."""
    engine = _fresh_engine()
    SQLModel.metadata.create_all(engine)
    ensure_schema_migrations(engine)
    ensure_schema_migrations(engine)
    # Still has the column, no errors.
    assert "kindle_asin" in _columns(engine, "book")


def test_migration_does_not_overwrite_existing_kindle_asin() -> None:
    """If a row already has kindle_asin set, backfill must not clobber it."""
    engine = _fresh_engine()
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        b = Book(title="T", author="A", document_tags="asin:OTHER", kindle_asin="MANUAL")
        s.add(b)
        s.commit()
        s.refresh(b)
        bid = b.id

    ensure_schema_migrations(engine)

    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT kindle_asin FROM book WHERE id = :id"), {"id": bid}
        ).one()
        assert row[0] == "MANUAL"
