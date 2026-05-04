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


# ── ApiToken NOT NULL constraint rebuild ──────────────────────────────────


def _replace_apitoken_with_legacy_schema(engine) -> None:
    """Drop the model-emitted apitoken and recreate it with the pre-Phase-4
    schema (token VARCHAR NOT NULL). Other tables (book, user, …) stay."""
    with engine.begin() as conn:
        conn.execute(text("DROP TABLE IF EXISTS apitoken"))
        conn.execute(
            text(
                "CREATE TABLE apitoken (\n"
                "    id INTEGER NOT NULL,\n"
                "    token VARCHAR NOT NULL,\n"
                "    name VARCHAR NOT NULL,\n"
                "    user_id INTEGER NOT NULL,\n"
                "    created_at DATETIME NOT NULL,\n"
                "    last_used_at DATETIME,\n"
                "    PRIMARY KEY (id),\n"
                "    FOREIGN KEY(user_id) REFERENCES user (id)\n"
                ")"
            )
        )
        conn.execute(
            text("CREATE UNIQUE INDEX ix_apitoken_token ON apitoken (token)")
        )
        conn.execute(
            text("INSERT INTO user (id, email, password_hash) VALUES (1, 'a@b', 'x')")
        )
        conn.execute(
            text(
                "INSERT INTO apitoken (id, token, name, user_id, created_at) "
                "VALUES (1, 'plaintext-legacy', 'old', 1, '2025-01-01 00:00:00')"
            )
        )


def test_migration_drops_not_null_on_apitoken_token() -> None:
    """A legacy DB declared apitoken.token NOT NULL. New rows leave that
    column NULL (only token_hash + token_prefix are populated), so the
    migration must rebuild the table to relax the constraint. Symptom on
    a non-migrated production DB:
        sqlite3.IntegrityError: NOT NULL constraint failed: apitoken.token
    on every fresh INSERT.
    """
    engine = _fresh_engine()
    SQLModel.metadata.create_all(engine)  # all model tables incl. book
    _replace_apitoken_with_legacy_schema(engine)

    # Sanity: pre-migration, the column is NOT NULL.
    with engine.connect() as conn:
        col = next(r for r in conn.execute(text("PRAGMA table_info(apitoken)")).all() if r[1] == "token")
        assert col[3] == 1  # notnull == True

    ensure_schema_migrations(engine)

    # Post-migration: notnull cleared, indexes preserved, row preserved.
    with engine.connect() as conn:
        col = next(r for r in conn.execute(text("PRAGMA table_info(apitoken)")).all() if r[1] == "token")
        assert col[3] == 0  # nullable now

        row = conn.execute(
            text("SELECT id, token, name, user_id FROM apitoken WHERE id = 1")
        ).one()
        assert row == (1, "plaintext-legacy", "old", 1)

        # New-style rows must now insert successfully with token=NULL.
        conn.execute(
            text(
                "INSERT INTO apitoken (token, name, user_id, created_at, "
                "token_prefix, token_hash, scopes) "
                "VALUES (NULL, 'new-token', 1, '2026-05-04 00:00:00', "
                "'fw_abc', 'hash', 'kindle:import')"
            )
        )
        cnt = conn.execute(text("SELECT COUNT(*) FROM apitoken")).scalar()
        assert cnt == 2


def test_apitoken_rebuild_idempotent_on_already_nullable_db() -> None:
    """A DB that already has token nullable should be a no-op the second time."""
    engine = _fresh_engine()
    SQLModel.metadata.create_all(engine)
    ensure_schema_migrations(engine)
    ensure_schema_migrations(engine)
    with engine.connect() as conn:
        col = next(r for r in conn.execute(text("PRAGMA table_info(apitoken)")).all() if r[1] == "token")
        assert col[3] == 0
