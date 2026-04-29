"""
Kindle notebook JSON importer.

Pure-function importer (no FastAPI dependencies) that consumes JSON produced by
the Kindle scraper (see `docs/KINDLE_JSON_SCHEMA.md` for the contract).

The companion FastAPI route lives in `app/routers/importer.py`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import IO, Any, Optional, Union

import jsonschema
from sqlmodel import Session, select

from app.models import Book, Highlight
from app.routers.importer import get_or_create_book, parse_readwise_datetime


logger = logging.getLogger(__name__)


SUPPORTED_SCHEMA_MAJOR = "1"
SUPPORTED_SOURCE = "kindle_notebook"

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "kindle-export-v1.schema.json"
_SCHEMA = json.loads(_SCHEMA_PATH.read_text())
_VALIDATOR = jsonschema.Draft202012Validator(_SCHEMA)


@dataclass(frozen=True)
class KindleImportResult:
    """Aggregated counts and per-row error messages from a single import call."""
    books_created: int = 0
    books_matched: int = 0
    highlights_created: int = 0
    highlights_skipped_duplicates: int = 0
    errors: list[str] = field(default_factory=list)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _read_payload(file_obj: Union[IO[bytes], IO[str]]) -> dict[str, Any]:
    """Decode the uploaded file (bytes or text stream) into a JSON dict."""
    raw = file_obj.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def _validate_envelope(payload: dict[str, Any]) -> None:
    """Raise ValueError if schema_version major or source is unsupported, OR
    if the envelope fails the strict shared JSON Schema."""
    schema_version = payload.get("schema_version", "")
    if not isinstance(schema_version, str) or "." not in schema_version:
        raise ValueError(
            f"Invalid schema_version: {schema_version!r} "
            f"(expected major == {SUPPORTED_SCHEMA_MAJOR!r})"
        )
    major = schema_version.split(".", 1)[0]
    if major != SUPPORTED_SCHEMA_MAJOR:
        raise ValueError(
            f"Unsupported schema_version major: {major!r} "
            f"(this importer supports {SUPPORTED_SCHEMA_MAJOR!r}.x)"
        )

    source = payload.get("source")
    if source != SUPPORTED_SOURCE:
        raise ValueError(
            f"Unsupported source: {source!r} (expected {SUPPORTED_SOURCE!r})"
        )

    schema_errors = sorted(_VALIDATOR.iter_errors(payload), key=lambda e: list(e.absolute_path))
    if schema_errors:
        first = schema_errors[0]
        path = ".".join(str(p) for p in first.absolute_path) or "(root)"
        raise ValueError(f"Schema validation failed at {path}: {first.message}")


def _merge_asin_tag(existing: Optional[str], asin: str) -> str:
    """Return existing document_tags with `asin:<value>` merged in (no duplicates)."""
    asin_tag = f"asin:{asin}"
    if not existing:
        return asin_tag
    parts = [t.strip() for t in existing.split(",") if t.strip()]
    if asin_tag in parts:
        return existing
    parts.append(asin_tag)
    return ",".join(parts)


def _resolve_location(
    location: Any, page: Any
) -> tuple[Optional[int], Optional[str]]:
    """
    Map (location, page) per docs/KINDLE_JSON_SCHEMA.md → (location_int, location_type).

    Prefer Kindle Location; fall back to page when location is null.
    """
    if isinstance(location, int):
        return location, "kindle_location"
    if isinstance(page, int):
        return page, "page"
    return None, None


# ── Main entry point ─────────────────────────────────────────────────────────


def import_kindle_notebook_json(
    file_obj: Union[IO[bytes], IO[str]],
    session: Session,
    user_id: int,
    *,
    default_created_at: Optional[datetime] = None,
) -> KindleImportResult:
    """
    Import a Kindle notebook JSON export into the database.

    Per-row errors are appended to `result.errors` and processing continues
    (best-effort import). Schema-level errors raise ValueError.
    """
    payload = _read_payload(file_obj)
    _validate_envelope(payload)

    # Resolve fallback timestamp: explicit arg > exported_at > None.
    fallback_created_at = default_created_at
    if fallback_created_at is None:
        exported_at_str = payload.get("exported_at")
        if isinstance(exported_at_str, str):
            fallback_created_at = parse_readwise_datetime(exported_at_str)

    books_created = 0
    books_matched = 0
    highlights_created = 0
    highlights_skipped_duplicates = 0
    errors: list[str] = []

    for book_idx, book_data in enumerate(payload.get("books", []) or []):
        try:
            counts = _import_book(
                book_data=book_data,
                session=session,
                user_id=user_id,
                fallback_created_at=fallback_created_at,
                errors=errors,
            )
        except Exception as exc:  # defensive: never let one book kill the run
            msg = f"book[{book_idx}]: unexpected error: {exc}"
            logger.exception(msg)
            errors.append(msg)
            continue

        if counts is None:
            continue
        created, matched, h_created, h_dupes = counts
        books_created += created
        books_matched += matched
        highlights_created += h_created
        highlights_skipped_duplicates += h_dupes

    return KindleImportResult(
        books_created=books_created,
        books_matched=books_matched,
        highlights_created=highlights_created,
        highlights_skipped_duplicates=highlights_skipped_duplicates,
        errors=errors,
    )


# ── Per-book orchestration ───────────────────────────────────────────────────


def _import_book(
    *,
    book_data: dict[str, Any],
    session: Session,
    user_id: int,
    fallback_created_at: Optional[datetime],
    errors: list[str],
) -> Optional[tuple[int, int, int, int]]:
    """
    Import one book and its highlights.

    Returns (books_created, books_matched, highlights_created, highlights_skipped_duplicates),
    or None when the book is skipped entirely (no row touched).
    """
    title = (book_data.get("title") or "").strip()
    asin = (book_data.get("asin") or "").strip()

    if not title:
        msg = f"Skipping book with missing title (asin={asin!r})"
        logger.warning(msg)
        errors.append(msg)
        return None
    if not asin:
        msg = f"Skipping book {title!r}: missing asin"
        logger.warning(msg)
        errors.append(msg)
        return None

    raw_highlights = book_data.get("highlights") or []
    if not raw_highlights:
        # Per the documented behavior in tests: do not create empty Book rows.
        logger.info("Skipping book %r: no highlights", title)
        return None

    author_raw = book_data.get("author")
    author = author_raw.strip() if isinstance(author_raw, str) and author_raw.strip() else None
    cover_url_raw = book_data.get("cover_url")
    cover_url = cover_url_raw.strip() if isinstance(cover_url_raw, str) and cover_url_raw.strip() else None

    # Dedup priority:
    #   1. existing book carrying an `asin:<asin>` tag — most reliable, survives
    #      title rewrites in Amazon's library (e.g. " (Japanese Edition)" added)
    #   2. (title, author) match — covers re-imports of books predating ASIN tagging
    #   3. otherwise: create a new book
    existing = _find_existing_book_by_asin(session, asin=asin)
    if existing is None:
        existing = _find_existing_book(session, title=title, author=author)

    if existing is not None:
        is_new = False
        book = existing
        # Title may have changed in Amazon's library; trust the latest scrape.
        if book.title != title:
            book.title = title
            session.add(book)
        if author is not None and book.author != author:
            book.author = author
            session.add(book)
    else:
        is_new = True
        book = get_or_create_book(
            session=session,
            title=title,
            author=author,
            document_tags=f"asin:{asin}",
        )
        if book is None:  # pragma: no cover — only on empty title
            msg = f"Failed to materialise book {title!r}"
            errors.append(msg)
            return None

    # Always set kindle_asin (Phase 3 column), and keep the document_tags
    # mirror in lockstep so older readers (until everything is migrated) still
    # see the asin tag.
    if book.kindle_asin != asin:
        book.kindle_asin = asin
        session.add(book)
    merged_tags = _merge_asin_tag(book.document_tags, asin)
    if merged_tags != (book.document_tags or ""):
        book.document_tags = merged_tags
        session.add(book)

    # Cover only on new-book creation per schema.
    if is_new and cover_url and not book.cover_image_url:
        book.cover_image_url = cover_url
        book.cover_image_source = "kindle"
        session.add(book)

    session.commit()
    session.refresh(book)

    h_created, h_dupes = _import_highlights(
        raw_highlights=raw_highlights,
        book=book,
        session=session,
        user_id=user_id,
        fallback_created_at=fallback_created_at,
        errors=errors,
    )

    return (1 if is_new else 0, 0 if is_new else 1, h_created, h_dupes)


def _find_existing_book(
    session: Session, *, title: str, author: Optional[str]
) -> Optional[Book]:
    """Return the existing book row matching (title, author), or None."""
    stmt = select(Book).where(Book.title == title)
    if author is None:
        stmt = stmt.where(Book.author == None)  # noqa: E711 — SQLAlchemy idiom
    else:
        stmt = stmt.where(Book.author == author)
    return session.exec(stmt).first()


def _find_existing_book_by_asin(session: Session, *, asin: str) -> Optional[Book]:
    """Return the existing Book matching ``asin``.

    Lookup order:
      1. Dedicated ``kindle_asin`` column (Phase 3 — added by the lightweight
         schema migration in ``app.db.ensure_schema_migrations``).
      2. Legacy ``document_tags`` entry shaped ``asin:<value>``. This handles
         rows that pre-date the migration on a long-lived deployment where
         the import has run before the FreeWise binary was upgraded.

    Tag-based matching uses ``LIKE '%asin:%'`` then verifies token boundaries
    in Python so e.g. ``asin:B07F`` does not collide with ``asin:B07FCMBLM6XX``.
    """
    if not asin:
        return None

    by_column = session.exec(
        select(Book).where(Book.kindle_asin == asin)
    ).first()
    if by_column is not None:
        return by_column

    needle = f"asin:{asin}"
    stmt = select(Book).where(Book.document_tags.is_not(None)).where(  # type: ignore[union-attr]
        Book.document_tags.contains(needle)  # type: ignore[union-attr]
    )
    for candidate in session.exec(stmt):
        tags = (candidate.document_tags or "").split(",")
        if any(tag.strip() == needle for tag in tags):
            return candidate
    return None


def _import_highlights(
    *,
    raw_highlights: list[dict[str, Any]],
    book: Book,
    session: Session,
    user_id: int,
    fallback_created_at: Optional[datetime],
    errors: list[str],
) -> tuple[int, int]:
    """Import highlights for a single book. Returns (created, skipped_duplicates)."""
    created = 0
    duplicates = 0

    for h_idx, h in enumerate(raw_highlights):
        try:
            created_one, was_dupe = _import_one_highlight(
                h=h,
                book=book,
                session=session,
                user_id=user_id,
                fallback_created_at=fallback_created_at,
                errors=errors,
                h_idx=h_idx,
            )
        except Exception as exc:
            msg = (
                f"book[{book.title!r}].highlight[{h_idx}]: unexpected error: {exc}"
            )
            logger.exception(msg)
            errors.append(msg)
            continue

        if created_one:
            created += 1
        elif was_dupe:
            duplicates += 1

    return created, duplicates


def _import_one_highlight(
    *,
    h: dict[str, Any],
    book: Book,
    session: Session,
    user_id: int,
    fallback_created_at: Optional[datetime],
    errors: list[str],
    h_idx: int,
) -> tuple[bool, bool]:
    """
    Import a single highlight row.

    Returns (was_created, was_duplicate). Both False when the row was skipped
    due to validation errors.
    """
    text_raw = h.get("text")
    text = text_raw.strip() if isinstance(text_raw, str) else ""
    h_id = h.get("id")

    if not text:
        msg = (
            f"Skipping highlight #{h_idx} in book {book.title!r}: missing text"
        )
        logger.warning(msg)
        errors.append(msg)
        return (False, False)
    if not h_id:
        msg = (
            f"Skipping highlight #{h_idx} in book {book.title!r}: missing id"
        )
        logger.warning(msg)
        errors.append(msg)
        return (False, False)

    location, location_type = _resolve_location(h.get("location"), h.get("page"))

    note_raw = h.get("note")
    note = note_raw.strip() if isinstance(note_raw, str) and note_raw.strip() else None

    # Dedup on (book_id, text, location)
    dup_stmt = select(Highlight).where(
        Highlight.book_id == book.id,
        Highlight.text == text,
        Highlight.location == location,
    )
    if session.exec(dup_stmt).first() is not None:
        return (False, True)

    # Resolve created_at
    created_at: Optional[datetime] = None
    raw_ts = h.get("created_at")
    if isinstance(raw_ts, str) and raw_ts.strip():
        created_at = parse_readwise_datetime(raw_ts)
    if created_at is None:
        created_at = fallback_created_at

    highlight = Highlight(
        text=text,
        note=note,
        book_id=book.id,
        created_at=created_at,
        location=location,
        location_type=location_type,
        user_id=user_id,
    )
    session.add(highlight)
    session.commit()
    session.refresh(highlight)
    return (True, False)
