"""Tests for app.services.kindle_import_status.get_status."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.models import Book, Highlight
from app.services.kindle_import_status import KindleImportStatus, get_status


def test_disabled_when_env_unset(db, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINDLE_IMPORTS_DIR", raising=False)

    status = get_status(db)

    assert isinstance(status, KindleImportStatus)
    assert status.enabled is False
    assert status.imports_dir is None
    assert status.last_imported_at is None
    assert status.last_imported_filename is None
    assert status.last_imported_books is None
    assert status.last_imported_highlights is None
    assert status.pending_files == 0
    assert status.processed_files == 0
    assert status.total_kindle_books == 0
    assert status.total_kindle_highlights == 0


def test_enabled_with_no_files(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))

    status = get_status(db)

    assert status.enabled is True
    assert status.imports_dir == str(tmp_path)
    assert status.pending_files == 0
    assert status.processed_files == 0
    assert status.last_imported_at is None
    assert status.last_imported_filename is None
    assert status.last_imported_books is None
    assert status.last_imported_highlights is None
    assert status.total_kindle_books == 0
    assert status.total_kindle_highlights == 0


def test_reads_last_imported_from_processed_dir(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    imports_dir = tmp_path / "imports"
    processed_dir = imports_dir / "processed"
    processed_dir.mkdir(parents=True)

    payload = {
        "schema_version": "1.0",
        "books": [
            {
                "asin": "A1",
                "title": "B1",
                "highlights": [
                    {"id": "h1", "text": "x"},
                    {"id": "h2", "text": "y"},
                    {"id": "h3", "text": "z"},
                ],
            },
            {
                "asin": "A2",
                "title": "B2",
                "highlights": [
                    {"id": "h4", "text": "p"},
                    {"id": "h5", "text": "q"},
                ],
            },
        ],
    }
    (processed_dir / "foo.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(imports_dir))

    status = get_status(db)

    assert status.enabled is True
    assert status.last_imported_filename == "foo.json"
    assert status.last_imported_books == 2
    assert status.last_imported_highlights == 5
    assert status.last_imported_at is not None
    assert status.processed_files == 1
    assert status.pending_files == 0


def test_total_kindle_books_counts_only_kindle_asin_set(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))

    kindle_book_a = Book(title="Kindle A", kindle_asin="ASIN1")
    kindle_book_b = Book(title="Kindle B", kindle_asin="ASIN2")
    non_kindle = Book(title="Manual", kindle_asin=None)
    db.add(kindle_book_a)
    db.add(kindle_book_b)
    db.add(non_kindle)
    db.commit()
    db.refresh(kindle_book_a)
    db.refresh(kindle_book_b)
    db.refresh(non_kindle)

    db.add(Highlight(text="h1", book_id=kindle_book_a.id, user_id=1))
    db.add(Highlight(text="h2", book_id=kindle_book_a.id, user_id=1))
    db.add(Highlight(text="h3", book_id=kindle_book_b.id, user_id=1))
    db.add(Highlight(text="h4", book_id=non_kindle.id, user_id=1))
    db.commit()

    status = get_status(db)

    assert status.total_kindle_books == 2
    assert status.total_kindle_highlights == 3
