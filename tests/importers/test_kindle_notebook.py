"""
Tests for the Kindle notebook JSON importer.

Schema contract: docs/KINDLE_JSON_SCHEMA.md
Fixture: tests/fixtures/kindle_notebook_sample.json
"""
import io
import json
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import select

from app.importers.kindle_notebook import (
    KindleImportResult,
    import_kindle_notebook_json,
)
from app.models import Book, Highlight


FIXTURE_PATH = Path(__file__).resolve().parent.parent / "fixtures" / "kindle_notebook_sample.json"


def _open_fixture() -> io.BytesIO:
    """Return a BytesIO containing the canonical sample fixture."""
    return io.BytesIO(FIXTURE_PATH.read_bytes())


def _to_bytes(payload: dict) -> io.BytesIO:
    return io.BytesIO(json.dumps(payload).encode("utf-8"))


# ── Happy-path round-trip ────────────────────────────────────────────────────


def test_imports_books_and_highlights_from_fixture(db):
    result = import_kindle_notebook_json(_open_fixture(), db, user_id=1)

    assert isinstance(result, KindleImportResult)
    # Sapiens (3 highlights) + TFS (1 highlight) = 2 books with content.
    # The empty-highlights book MUST NOT create a Book row (documented behavior).
    assert result.books_created == 2
    assert result.books_matched == 0
    assert result.highlights_created == 4
    assert result.highlights_skipped_duplicates == 0
    assert result.errors == []

    books = db.exec(select(Book)).all()
    titles = {b.title for b in books}
    assert "Sapiens: A Brief History of Humankind" in titles
    assert "Thinking, Fast and Slow" in titles
    assert "Book Without Highlights" not in titles
    assert len(books) == 2

    sapiens = db.exec(select(Book).where(Book.title.like("Sapiens%"))).first()
    assert "asin:B07FCMBLM6" in (sapiens.document_tags or "")
    assert sapiens.cover_image_url == "https://m.media-amazon.com/images/I/sapiens.jpg"
    assert sapiens.cover_image_source == "kindle"

    # location_type mapping — Sapiens h1 has both location and page → kindle_location wins
    h1 = db.exec(
        select(Highlight).where(Highlight.text.like("The cognitive revolution%"))
    ).first()
    assert h1.location == 1234
    assert h1.location_type == "kindle_location"

    # h3 has location=null, page=87 → falls back to page
    h3 = db.exec(
        select(Highlight).where(Highlight.text.like("We did not domesticate%"))
    ).first()
    assert h3.location == 87
    assert h3.location_type == "page"

    highlights = db.exec(select(Highlight)).all()
    assert len(highlights) == 4
    assert all(h.user_id == 1 for h in highlights)


def test_idempotent_reimport(db):
    import_kindle_notebook_json(_open_fixture(), db, user_id=1)
    result2 = import_kindle_notebook_json(_open_fixture(), db, user_id=1)

    assert result2.books_created == 0
    assert result2.books_matched == 2
    assert result2.highlights_created == 0
    assert result2.highlights_skipped_duplicates == 4

    assert len(db.exec(select(Book)).all()) == 2
    assert len(db.exec(select(Highlight)).all()) == 4


# ── Validation ───────────────────────────────────────────────────────────────


def test_rejects_unsupported_schema_version(db):
    payload = {
        "schema_version": "99.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [],
    }
    with pytest.raises(ValueError):
        import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)


def test_rejects_unsupported_source(db):
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "evernote",
        "books": [],
    }
    with pytest.raises(ValueError):
        import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)


# ── Per-record best-effort behavior ──────────────────────────────────────────


def test_skips_book_missing_asin(db):
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": None,
                "title": "Bad Book",
                "author": "Nobody",
                "highlights": [
                    {"id": "x", "text": "irrelevant", "location": 1, "page": None},
                ],
            },
            {
                "asin": "B0VALID0001",
                "title": "Good Book",
                "author": "Author",
                "highlights": [
                    {"id": "g1", "text": "good highlight", "location": 5, "page": None},
                ],
            },
        ],
    }
    result = import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    assert result.books_created == 1
    assert result.highlights_created == 1
    assert any("asin" in e.lower() or "skip" in e.lower() for e in result.errors)

    books = db.exec(select(Book)).all()
    assert len(books) == 1
    assert books[0].title == "Good Book"


def test_skips_highlight_missing_text(db):
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B0VALID0002",
                "title": "Mixed Book",
                "author": "Author",
                "highlights": [
                    {"id": "ok", "text": "good text", "location": 10, "page": None},
                    {"id": "bad", "text": None, "location": 20, "page": None},
                    {"id": None, "text": "no id", "location": 30, "page": None},
                ],
            },
        ],
    }
    result = import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    assert result.books_created == 1
    assert result.highlights_created == 1
    assert len(result.errors) >= 2  # one for missing text, one for missing id

    highlights = db.exec(select(Highlight)).all()
    assert len(highlights) == 1
    assert highlights[0].text == "good text"


def test_created_at_fallback_to_exported_at(db):
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T12:34:56Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B0FALLBACK01",
                "title": "Fallback Book",
                "author": "Author",
                "highlights": [
                    {
                        "id": "fb1",
                        "text": "highlight without timestamp",
                        "location": 1,
                        "page": None,
                        "created_at": None,
                    },
                ],
            },
        ],
    }
    import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    h = db.exec(select(Highlight)).first()
    assert h.created_at is not None
    assert h.created_at.year == 2026
    assert h.created_at.month == 4
    assert h.created_at.day == 25
    assert h.created_at.hour == 12
    assert h.created_at.minute == 34


def test_book_without_highlights_does_not_create_book(db):
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B0EMPTY00001",
                "title": "Empty Book",
                "author": None,
                "highlights": [],
            },
        ],
    }
    result = import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    assert result.books_created == 0
    assert result.highlights_created == 0
    assert db.exec(select(Book)).all() == []


# ── Sanity: does not corrupt existing tags ───────────────────────────────────


def test_preserves_existing_document_tags_when_matching_book(db):
    """If a book already exists with document_tags, the ASIN tag should be merged in."""
    pre_existing = Book(
        title="Sapiens: A Brief History of Humankind",
        author="Yuval Noah Harari",
        document_tags="history,anthropology",
    )
    db.add(pre_existing)
    db.commit()
    db.refresh(pre_existing)

    import_kindle_notebook_json(_open_fixture(), db, user_id=1)

    db.refresh(pre_existing)
    tags = pre_existing.document_tags or ""
    assert "history" in tags
    assert "anthropology" in tags
    assert "asin:B07FCMBLM6" in tags
