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


def test_rejects_envelope_with_empty_asin(db):
    """An envelope containing a book with empty asin is rejected by the strict
    JSON Schema validator before any DB write.

    The shared schema requires asin: string with minLength:1. An empty or null
    asin is therefore a schema-level error, not a per-book soft skip.
    """
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "",
                "title": "Bad Book",
                "author": "Nobody",
                "cover_url": None,
                "highlights": [
                    {
                        "id": "x",
                        "text": "irrelevant",
                        "note": None,
                        "color": None,
                        "location": 1,
                        "page": None,
                        "created_at": None,
                    }
                ],
            },
        ],
    }
    with pytest.raises(ValueError, match="asin"):
        import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    # No DB writes should have occurred.
    assert db.exec(select(Book)).all() == []


def test_skips_highlight_missing_text(db):
    # The strict envelope schema requires id (type:string, minLength:1) and
    # text (type:string, allows "").  Use empty string for text to exercise
    # the per-highlight skip logic without violating the schema.
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B0VALID0002",
                "title": "Mixed Book",
                "author": "Author",
                "cover_url": None,
                "highlights": [
                    {
                        "id": "ok",
                        "text": "good text",
                        "note": None,
                        "color": None,
                        "location": 10,
                        "page": None,
                        "created_at": None,
                    },
                    {
                        "id": "bad-empty-text",
                        "text": "",
                        "note": None,
                        "color": None,
                        "location": 20,
                        "page": None,
                        "created_at": None,
                    },
                    {
                        "id": "bad-whitespace-text",
                        "text": "   ",
                        "note": None,
                        "color": None,
                        "location": 30,
                        "page": None,
                        "created_at": None,
                    },
                ],
            },
        ],
    }
    result = import_kindle_notebook_json(_to_bytes(payload), db, user_id=1)

    assert result.books_created == 1
    assert result.highlights_created == 1
    assert len(result.errors) >= 2  # one per empty/whitespace-only text

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


# ── ASIN-based dedup (Phase 3 prep) ──────────────────────────────────────────


def _payload_one_book(*, asin="B07FCMBLM6", title="Sapiens", author="Yuval Noah Harari"):
    return {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T12:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": asin,
                "title": title,
                "author": author,
                "cover_url": None,
                "highlights": [
                    {
                        "id": "QID:h1",
                        "text": "the cognitive revolution",
                        "note": None,
                        "color": "yellow",
                        "location": 1,
                        "page": None,
                        "created_at": None,
                    }
                ],
            }
        ],
    }


def test_dedup_prefers_asin_over_title_when_title_changes(db):
    """If Amazon rewrites the title, the ASIN tag still matches the same book."""
    import_kindle_notebook_json(
        _to_bytes(_payload_one_book(title="Sapiens")), db, user_id=1
    )
    initial = db.exec(select(Book)).one()
    initial_id = initial.id

    # Re-import with a different title but the same ASIN — should match the
    # existing row by ASIN, not create a new one.
    import_kindle_notebook_json(
        _to_bytes(_payload_one_book(title="Sapiens (Revised Edition)")),
        db,
        user_id=1,
    )

    rows = db.exec(select(Book)).all()
    assert len(rows) == 1, f"expected 1 book after rename, got {len(rows)}"
    assert rows[0].id == initial_id
    assert rows[0].title == "Sapiens (Revised Edition)"  # title is updated


def test_dedup_falls_back_to_title_when_no_asin_tag_yet(db):
    """A pre-existing book without the ASIN tag still matches by (title, author)
    — backwards-compatible with rows imported before ASIN tagging existed."""
    pre_existing = Book(
        title="Sapiens",
        author="Yuval Noah Harari",
        document_tags=None,  # no asin tag yet
    )
    db.add(pre_existing)
    db.commit()
    db.refresh(pre_existing)
    pre_id = pre_existing.id

    import_kindle_notebook_json(_to_bytes(_payload_one_book()), db, user_id=1)

    rows = db.exec(select(Book)).all()
    assert len(rows) == 1
    assert rows[0].id == pre_id
    # ASIN tag is now backfilled
    assert "asin:B07FCMBLM6" in (rows[0].document_tags or "")


def test_dedup_does_not_match_substring_asin(db):
    """asin:B07F should NOT collide with asin:B07FCMBLM6."""
    longer = Book(
        title="Some Book",
        author=None,
        document_tags="asin:B07FCMBLM6XX",  # superstring
    )
    db.add(longer)
    db.commit()
    db.refresh(longer)
    longer_id = longer.id

    # Import with the shorter ASIN — should NOT match the longer one.
    import_kindle_notebook_json(_to_bytes(_payload_one_book(asin="B07F")), db, user_id=1)

    rows = db.exec(select(Book)).all()
    assert len(rows) == 2, f"expected 2 distinct books, got {len(rows)}"
    # Original survives untouched
    db.refresh(longer)
    assert longer.id == longer_id
    assert longer.document_tags == "asin:B07FCMBLM6XX"


# ── C.3: Strict JSON Schema validation ───────────────────────────────────────


def test_importer_rejects_envelope_failing_schema(db):
    """Envelope missing required `books` field is rejected before any DB write."""
    bad = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        # books missing
    }
    with pytest.raises(ValueError, match="books"):
        import_kindle_notebook_json(io.BytesIO(json.dumps(bad).encode()), db, user_id=1)


def test_importer_rejects_book_with_no_asin(db):
    bad = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {"title": "No ASIN", "highlights": []}
        ],
    }
    with pytest.raises(ValueError, match="asin"):
        import_kindle_notebook_json(io.BytesIO(json.dumps(bad).encode()), db, user_id=1)


# ── C.4: Structured errors ────────────────────────────────────────────────────


def test_importer_partial_failure_returns_structured_errors(db, monkeypatch):
    """When one book raises, errors is list[dict] with book_title + reason.
    The good book still imports; the bad one is skipped."""
    import app.importers.kindle_notebook as mod

    real_get_or_create = mod.get_or_create_book

    def flaky_get_or_create(session, *, title, author, **kwargs):
        if title == "Bad Book":
            raise RuntimeError("simulated dedup failure")
        return real_get_or_create(session, title=title, author=author, **kwargs)

    monkeypatch.setattr(mod, "get_or_create_book", flaky_get_or_create)

    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": [
            {
                "asin": "B07GOOD",
                "title": "Good Book",
                "author": "A",
                "cover_url": None,
                "highlights": [
                    {
                        "id": "QID:1",
                        "text": "valid highlight",
                        "note": None,
                        "color": None,
                        "location": 1,
                        "page": None,
                        "created_at": None,
                    }
                ],
            },
            {
                "asin": "B07BAD",
                "title": "Bad Book",
                "author": "B",
                "cover_url": None,
                "highlights": [
                    {
                        "id": "QID:99",
                        "text": "bad book highlight",
                        "note": None,
                        "color": None,
                        "location": 1,
                        "page": None,
                        "created_at": None,
                    }
                ],
            },
        ],
    }
    result = import_kindle_notebook_json(
        io.BytesIO(json.dumps(payload).encode()), db, user_id=1
    )

    assert result.highlights_created == 1
    assert result.books_created == 1

    # The bad book produced a structured error.
    assert len(result.errors) == 1
    err = result.errors[0]
    assert isinstance(err, dict)
    assert err["book_title"] == "Bad Book"
    assert "simulated dedup failure" in err["reason"]
