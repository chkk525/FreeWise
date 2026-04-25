"""Unit tests for app.services.kindle_import_watcher.scan_and_import."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
from sqlmodel import Session, select

from app.models import Book, Highlight
from app.services.kindle_import_watcher import (
    DEFAULT_INTERVAL_SECONDS,
    ScanResult,
    imports_dir_from_env,
    interval_seconds_from_env,
    scan_and_import,
    user_id_from_env,
)


def _write_kindle_json(path: Path, *, books: list[dict[str, Any]] | None = None) -> Path:
    payload = {
        "schema_version": "1.0",
        "exported_at": "2026-04-25T12:00:00Z",
        "source": "kindle_notebook",
        "books": books
        if books is not None
        else [
            {
                "asin": "B07FCMBLM6",
                "title": "Sapiens",
                "author": "Yuval Noah Harari",
                "cover_url": "https://example.invalid/sapiens.jpg",
                "highlights": [
                    {
                        "id": "QID:h1",
                        "text": "The cognitive revolution kicked off about 70,000 years ago.",
                        "note": None,
                        "color": "yellow",
                        "location": 1234,
                        "page": None,
                        "created_at": None,
                    }
                ],
            }
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_returns_empty_when_dir_missing(tmp_path: Path, db: Session) -> None:
    result = scan_and_import(
        imports_dir=tmp_path / "does-not-exist",
        session=db,
    )
    assert result == ScanResult(0, 0, 0, 0, 0, 0, 0, ())


def test_returns_empty_when_no_json_files(tmp_path: Path, db: Session) -> None:
    (tmp_path / "ignored.txt").write_text("not me")
    result = scan_and_import(
        imports_dir=tmp_path,
        session=db,
    )
    assert result.files_scanned == 0
    assert result.files_imported == 0


def test_imports_single_file_and_moves_to_processed(tmp_path: Path, db: Session) -> None:
    f = _write_kindle_json(tmp_path / "kindle_a.json")

    result = scan_and_import(imports_dir=tmp_path, session=db)

    assert result.files_scanned == 1
    assert result.files_imported == 1
    assert result.files_failed == 0
    assert result.books_created == 1
    assert result.highlights_created == 1
    assert not f.exists(), "source file should have been moved"
    assert (tmp_path / "processed" / "kindle_a.json").exists()
    assert db.exec(select(Book)).one().title == "Sapiens"
    assert db.exec(select(Highlight)).one().text.startswith("The cognitive revolution")


def test_imports_multiple_files_in_mtime_order(tmp_path: Path, db: Session) -> None:
    a = _write_kindle_json(tmp_path / "scrape_a.json")
    b = _write_kindle_json(
        tmp_path / "scrape_b.json",
        books=[
            {
                "asin": "B00KQYTBNW",
                "title": "Thinking, Fast and Slow",
                "author": "Daniel Kahneman",
                "cover_url": None,
                "highlights": [
                    {
                        "id": "QID:tfs1",
                        "text": "Nothing in life is as important as you think it is.",
                        "note": None,
                        "color": "yellow",
                        "location": 2031,
                        "page": None,
                        "created_at": None,
                    }
                ],
            }
        ],
    )
    older = a.stat().st_mtime - 60
    os.utime(b, (older, older))

    result = scan_and_import(imports_dir=tmp_path, session=db)

    assert result.files_imported == 2
    assert result.books_created == 2
    assert result.highlights_created == 2
    assert (tmp_path / "processed" / "scrape_a.json").exists()
    assert (tmp_path / "processed" / "scrape_b.json").exists()


def test_idempotent_after_processing(tmp_path: Path, db: Session) -> None:
    _write_kindle_json(tmp_path / "first_run.json")
    first = scan_and_import(imports_dir=tmp_path, session=db)
    assert first.files_imported == 1
    assert first.books_created == 1

    second = scan_and_import(imports_dir=tmp_path, session=db)
    assert second.files_imported == 0
    assert second.files_scanned == 0


def test_failed_file_left_in_place_and_counted(tmp_path: Path, db: Session) -> None:
    bad = tmp_path / "broken.json"
    bad.write_text("{ this is not valid JSON")

    result = scan_and_import(imports_dir=tmp_path, session=db)

    assert result.files_scanned == 1
    assert result.files_failed == 1
    assert result.files_imported == 0
    assert bad.exists(), "failed file should NOT be moved (so user can inspect)"
    assert any("broken.json" in e for e in result.errors)


def test_collision_in_processed_dir_is_disambiguated(tmp_path: Path, db: Session) -> None:
    processed = tmp_path / "processed"
    processed.mkdir()
    (processed / "scrape.json").write_text("{}")
    _write_kindle_json(tmp_path / "scrape.json")

    result = scan_and_import(imports_dir=tmp_path, session=db)
    assert result.files_imported == 1
    moved = list(processed.glob("scrape*.json"))
    assert len(moved) == 2, f"both files should coexist under processed/: {moved}"


def test_imports_dir_from_env_returns_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINDLE_IMPORTS_DIR", raising=False)
    assert imports_dir_from_env() is None


def test_imports_dir_from_env_returns_path_when_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))
    assert imports_dir_from_env() == tmp_path


def test_interval_clamps_minimum_to_60(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINDLE_IMPORT_INTERVAL_SECONDS", "30")
    assert interval_seconds_from_env() == 60


def test_interval_default_when_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KINDLE_IMPORT_INTERVAL_SECONDS", "soon")
    assert interval_seconds_from_env() == DEFAULT_INTERVAL_SECONDS


def test_user_id_default_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINDLE_IMPORT_USER_ID", raising=False)
    assert user_id_from_env() == 1
