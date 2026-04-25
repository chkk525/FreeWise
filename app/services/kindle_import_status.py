"""Read-side service for the dashboard "Latest Kindle import" card.

Aggregates filesystem state (pending / processed JSON files in the imports
directory) with database state (count of Kindle-sourced books and highlights,
identified by ``Book.kindle_asin IS NOT NULL``) into a single immutable
``KindleImportStatus`` value object.

Disabled (``enabled=False``) when the ``KINDLE_IMPORTS_DIR`` env var is unset
or points at a path that does not exist on disk.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlmodel import Session, select

from app.models import Book, Highlight


@dataclass(frozen=True)
class KindleImportStatus:
    """Snapshot of Kindle import state for the dashboard card."""

    enabled: bool
    imports_dir: Optional[str]
    last_imported_at: Optional[str]  # ISO-8601 string for JSON
    last_imported_filename: Optional[str]
    last_imported_books: Optional[int]
    last_imported_highlights: Optional[int]
    pending_files: int
    processed_files: int
    total_kindle_books: int
    total_kindle_highlights: int


def _disabled_status(imports_dir: Optional[Path]) -> KindleImportStatus:
    return KindleImportStatus(
        enabled=False,
        imports_dir=str(imports_dir) if imports_dir is not None else None,
        last_imported_at=None,
        last_imported_filename=None,
        last_imported_books=None,
        last_imported_highlights=None,
        pending_files=0,
        processed_files=0,
        total_kindle_books=0,
        total_kindle_highlights=0,
    )


def _read_last_processed(processed_dir: Path) -> tuple[
    Optional[str], Optional[str], Optional[int], Optional[int]
]:
    """Return (iso_mtime, filename, books, highlights) for the newest JSON, or all None."""
    if not processed_dir.exists() or not processed_dir.is_dir():
        return None, None, None, None

    candidates = [
        p for p in processed_dir.glob("*.json") if p.is_file() and not p.is_symlink()
    ]
    if not candidates:
        return None, None, None, None

    newest = max(candidates, key=lambda p: p.stat().st_mtime)
    iso_mtime = (
        datetime.fromtimestamp(newest.stat().st_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )

    try:
        with newest.open("r", encoding="utf-8") as fh:
            payload = json.load(fh)
        books = payload.get("books") or []
        book_count = len(books)
        highlight_count = sum(len(b.get("highlights") or []) for b in books)
    except (OSError, json.JSONDecodeError, AttributeError, TypeError):
        return iso_mtime, newest.name, None, None

    return iso_mtime, newest.name, book_count, highlight_count


def get_status(session: Session) -> KindleImportStatus:
    """Build a :class:`KindleImportStatus` from env, filesystem, and DB."""
    # Imported lazily to avoid a circular import via app.routers.__init__
    # (kindle_import_watcher -> importer -> routers.__init__ -> dashboard -> here).
    from app.services import kindle_import_watcher

    imports_dir = kindle_import_watcher.imports_dir_from_env()
    if imports_dir is None or not imports_dir.exists() or not imports_dir.is_dir():
        return _disabled_status(imports_dir)

    pending_files = sum(
        1
        for p in imports_dir.glob("*.json")
        if p.is_file() and not p.is_symlink()
    )

    processed_dir = imports_dir / "processed"
    if processed_dir.exists() and processed_dir.is_dir():
        processed_files = sum(
            1
            for p in processed_dir.glob("*.json")
            if p.is_file() and not p.is_symlink()
        )
    else:
        processed_files = 0

    last_at, last_name, last_books, last_highlights = _read_last_processed(processed_dir)

    total_kindle_books = session.exec(
        select(func.count(Book.id)).where(Book.kindle_asin.is_not(None))
    ).one()
    total_kindle_highlights = session.exec(
        select(func.count(Highlight.id))
        .join(Book, Highlight.book_id == Book.id)
        .where(Book.kindle_asin.is_not(None))
    ).one()

    return KindleImportStatus(
        enabled=True,
        imports_dir=str(imports_dir),
        last_imported_at=last_at,
        last_imported_filename=last_name,
        last_imported_books=last_books,
        last_imported_highlights=last_highlights,
        pending_files=pending_files,
        processed_files=processed_files,
        total_kindle_books=int(total_kindle_books or 0),
        total_kindle_highlights=int(total_kindle_highlights or 0),
    )
