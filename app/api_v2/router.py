"""Readwise-compatible v2 API router.

Mounted under ``/api/v2``. Endpoints:

- ``GET  /api/v2/auth/``        — token-validation ping
- ``POST /api/v2/highlights/``  — create highlights from a Readwise-shaped body
- ``GET  /api/v2/highlights/``  — paginated list of highlights for the auth'd user
- ``GET  /api/v2/books/``       — paginated list of books with at least one highlight

Compatibility scope and known limits:

- Field names on the request side mirror Readwise exactly so existing clients
  (e.g. the FreeWise Chrome extension or third-party Readwise integrations)
  work unchanged.
- The response shape for ``POST /highlights/`` is **intentionally simpler**
  than Readwise's: we return ``{"created", "skipped_duplicates", "errors"}``
  rather than a list of book summaries. Clients that need the richer Readwise
  response should still receive a 2xx with these fields and ignore the diff.
- Dedup rule: ``(book_id, text, location)`` — same as the Kindle / Readwise
  CSV importer in :mod:`app.routers.importer`.
- ``source_url`` / ``source_type`` are folded into ``Book.document_tags`` as
  ``url:<value>`` / ``source:<value>`` entries, because the current ``Book``
  schema has no dedicated columns for them. The plan in
  ``docs/superpowers/plans/2026-04-19-readwise-api-and-chrome-extension.md``
  proposes adding those columns; see the issue tracker.
- ``highlight_url`` is accepted but ignored.
- Rate limiting, PATCH/DELETE, tag CRUD, daily-review and webhook endpoints
  from Readwise are deliberately out of scope for v1.
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session, func, select

from app.api_v2.auth import get_api_token
from app.api_v2.schemas import (
    BookListItem,
    HighlightCreatePayload,
    HighlightCreateResponse,
    HighlightDetail,
    HighlightInput,
    HighlightListItem,
    HighlightUpdatePayload,
    PaginatedResponse,
    StatsResponse,
)
from app.db import get_session
from app.models import ApiToken, Book, Highlight
from app.routers.importer import get_or_create_book

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2", tags=["api-v2"])


# ── Helpers ──────────────────────────────────────────────────────────────────

def _merge_document_tags(existing: Optional[str], extra: List[str]) -> Optional[str]:
    """Return a comma-joined tag string with ``extra`` appended (de-duplicated)."""
    if not extra:
        return existing
    current = [t.strip() for t in (existing or "").split(",") if t.strip()]
    seen = set(current)
    for tag in extra:
        if tag and tag not in seen:
            current.append(tag)
            seen.add(tag)
    return ",".join(current) if current else None


def _apply_source_metadata(
    book: Book,
    source_url: Optional[str],
    source_type: Optional[str],
) -> bool:
    """Attach ``url:<source_url>``/``source:<source_type>`` tags to ``book``.

    Returns True if ``book`` was modified.
    """
    extras: List[str] = []
    if source_url:
        extras.append(f"url:{source_url}")
    if source_type:
        extras.append(f"source:{source_type}")
    if not extras:
        return False
    new_tags = _merge_document_tags(book.document_tags, extras)
    if new_tags == book.document_tags:
        return False
    book.document_tags = new_tags
    return True


def _set_cover_if_missing(book: Book, image_url: Optional[str]) -> bool:
    """Set ``cover_image_url`` from the API payload if the book has none yet."""
    if not image_url or book.cover_image_url:
        return False
    book.cover_image_url = image_url
    book.cover_image_source = "readwise_api"
    return True


def _is_duplicate_highlight(
    session: Session,
    book_id: Optional[int],
    text: str,
    location: Optional[int],
) -> bool:
    """Match the Kindle/Readwise CSV dedup rule: ``(book_id, text, location)``."""
    stmt = select(Highlight).where(
        Highlight.book_id == book_id,
        Highlight.text == text,
        Highlight.location == location,
    )
    return session.exec(stmt).first() is not None


def _persist_highlight(
    session: Session,
    *,
    item: HighlightInput,
    user_id: int,
) -> tuple[bool, bool, Optional[str]]:
    """Persist one inbound highlight.

    Returns ``(created, was_duplicate, error_message)``. ``created`` and
    ``was_duplicate`` are mutually exclusive.
    """
    title = (item.title or "").strip()
    author = (item.author or "").strip() or None
    text = item.text.strip()
    if not text:
        return False, False, "empty highlight text"

    book: Optional[Book] = None
    if title:
        book = get_or_create_book(session=session, title=title, author=author)
        if book is not None:
            book_modified = False
            book_modified |= _apply_source_metadata(book, item.source_url, item.source_type)
            book_modified |= _set_cover_if_missing(book, item.image_url)
            if book_modified:
                session.add(book)
                session.commit()
                session.refresh(book)

    if _is_duplicate_highlight(session, book.id if book else None, text, item.location):
        return False, True, None

    created_at = item.highlighted_at
    if created_at is not None and created_at.tzinfo is not None:
        # Persist as naive UTC for consistency with the rest of the schema.
        created_at = created_at.replace(tzinfo=None)
    if created_at is None:
        created_at = datetime.now(UTC).replace(tzinfo=None)

    location_type = item.location_type if item.location is not None else None

    highlight = Highlight(
        text=text,
        note=item.note or None,
        book_id=book.id if book else None,
        created_at=created_at,
        location=item.location,
        location_type=location_type,
        user_id=user_id,
    )
    session.add(highlight)
    session.commit()
    session.refresh(highlight)
    return True, False, None


# ── Routes ───────────────────────────────────────────────────────────────────

@router.get("/auth/", status_code=status.HTTP_204_NO_CONTENT)
def auth_check(_token: ApiToken = Depends(get_api_token)) -> Response:
    """Match Readwise: 204 No Content when the token is valid."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/highlights/",
    status_code=status.HTTP_201_CREATED,
    response_model=HighlightCreateResponse,
)
def create_highlights(
    payload: HighlightCreatePayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightCreateResponse:
    """Create highlights from a Readwise-shaped batch body."""
    created = 0
    skipped = 0
    errors: List[str] = []

    for index, item in enumerate(payload.highlights):
        try:
            was_created, was_duplicate, err = _persist_highlight(
                session, item=item, user_id=token.user_id
            )
            if err:
                errors.append(f"highlights[{index}]: {err}")
                continue
            if was_created:
                created += 1
            elif was_duplicate:
                skipped += 1
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("api_v2: failed to persist highlight at index %s", index)
            errors.append(f"highlights[{index}]: {exc}")

    return HighlightCreateResponse(
        created=created, skipped_duplicates=skipped, errors=errors
    )


def _build_page_url(base_path: str, page: int, page_size: int, **extra: int) -> str:
    """Build a relative URL for the ``next``/``previous`` pagination links."""
    params = [f"page={page}", f"page_size={page_size}"]
    for key, value in extra.items():
        if value is not None:
            params.append(f"{key}={value}")
    return f"{base_path}?{'&'.join(params)}"


@router.get("/highlights/", response_model=PaginatedResponse)
def list_highlights(
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    book_id: Optional[int] = Query(default=None),
) -> PaginatedResponse:
    """Paginated list of highlights belonging to the authenticated user."""
    base_stmt = select(Highlight).where(Highlight.user_id == token.user_id)
    if book_id is not None:
        base_stmt = base_stmt.where(Highlight.book_id == book_id)

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    count = session.exec(count_stmt).one()

    rows_stmt = (
        base_stmt.order_by(Highlight.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = session.exec(rows_stmt).all()

    book_ids = {h.book_id for h in rows if h.book_id is not None}
    books_by_id: dict[int, Book] = {}
    if book_ids:
        books = session.exec(select(Book).where(Book.id.in_(book_ids))).all()
        books_by_id = {b.id: b for b in books}

    results: List[dict] = []
    for h in rows:
        book = books_by_id.get(h.book_id) if h.book_id is not None else None
        item = HighlightListItem(
            id=h.id,
            text=h.text,
            title=book.title if book else None,
            author=book.author if book else None,
            note=h.note,
            location=h.location,
            location_type=h.location_type,
            highlighted_at=h.created_at,
            book_id=h.book_id,
        )
        results.append(item.model_dump(mode="json"))

    next_url = (
        _build_page_url(
            "/api/v2/highlights/", page + 1, page_size,
            book_id=book_id if book_id is not None else None,
        )
        if page * page_size < count
        else None
    )
    prev_url = (
        _build_page_url(
            "/api/v2/highlights/", page - 1, page_size,
            book_id=book_id if book_id is not None else None,
        )
        if page > 1
        else None
    )

    return PaginatedResponse(count=count, next=next_url, previous=prev_url, results=results)


@router.get("/books/", response_model=PaginatedResponse)
def list_books(
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
) -> PaginatedResponse:
    """Paginated list of books that have at least one highlight by this user.

    Ordering: newest first by ``Book.id`` descending — i.e. most recently
    created books surface first. This is a deliberate choice (not Readwise's)
    documented here so callers can rely on it.
    """
    book_id_subq = (
        select(Highlight.book_id)
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.book_id.is_not(None))
        .distinct()
    )
    base_stmt = select(Book).where(Book.id.in_(book_id_subq))

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    count = session.exec(count_stmt).one()

    rows = session.exec(
        base_stmt.order_by(Book.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    # Pre-compute highlight counts in one query to avoid an N+1.
    counts_stmt = (
        select(Highlight.book_id, func.count(Highlight.id))
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.book_id.in_([b.id for b in rows] or [None]))
        .group_by(Highlight.book_id)
    )
    counts: dict[int, int] = {bid: cnt for bid, cnt in session.exec(counts_stmt).all()}

    results: List[dict] = []
    for b in rows:
        item = BookListItem(
            id=b.id,
            title=b.title,
            author=b.author,
            num_highlights=counts.get(b.id, 0),
            cover_image_url=b.cover_image_url,
        )
        results.append(item.model_dump(mode="json"))

    next_url = (
        _build_page_url("/api/v2/books/", page + 1, page_size)
        if page * page_size < count
        else None
    )
    prev_url = (
        _build_page_url("/api/v2/books/", page - 1, page_size)
        if page > 1
        else None
    )

    return PaginatedResponse(count=count, next=next_url, previous=prev_url, results=results)


# ── CLI / programmatic-use extensions (not part of Readwise's public API) ────


def _highlight_to_detail(h: Highlight, book: Optional[Book]) -> HighlightDetail:
    return HighlightDetail(
        id=h.id,
        text=h.text,
        title=book.title if book else None,
        author=book.author if book else None,
        note=h.note,
        location=h.location,
        location_type=h.location_type,
        highlighted_at=h.created_at,
        book_id=h.book_id,
        is_favorited=h.is_favorited,
        is_discarded=h.is_discarded,
    )


@router.get("/highlights/search", response_model=PaginatedResponse)
def search_highlights(
    q: str = Query(..., min_length=1, max_length=512),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    include_discarded: bool = Query(default=False),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Full-text LIKE search across this user's highlights (text + note).

    Not a Readwise endpoint — FreeWise extension under the same prefix.
    Wildcard chars in ``q`` are escaped so a ``%`` query matches a literal
    percent sign rather than every row.
    """
    needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{needle}%"
    base = select(Highlight).where(Highlight.user_id == token.user_id).where(
        Highlight.text.like(pattern, escape="\\")
        | Highlight.note.like(pattern, escape="\\")
    )
    if not include_discarded:
        base = base.where(Highlight.is_discarded == False)  # noqa: E712

    count = session.exec(
        select(func.count()).select_from(base.subquery())
    ).one()

    rows = session.exec(
        base.order_by(Highlight.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    book_ids = {h.book_id for h in rows if h.book_id is not None}
    books_by_id: dict[int, Book] = {}
    if book_ids:
        books = session.exec(select(Book).where(Book.id.in_(book_ids))).all()
        books_by_id = {b.id: b for b in books}

    results = [
        _highlight_to_detail(h, books_by_id.get(h.book_id) if h.book_id else None).model_dump(mode="json")
        for h in rows
    ]
    return PaginatedResponse(count=count, results=results)


@router.get("/highlights/{highlight_id}", response_model=HighlightDetail)
def get_highlight(
    highlight_id: int,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightDetail:
    """Single highlight detail. 404 if missing or not owned by this user."""
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    return _highlight_to_detail(h, book)


@router.patch("/highlights/{highlight_id}", response_model=HighlightDetail)
def update_highlight(
    highlight_id: int,
    payload: HighlightUpdatePayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightDetail:
    """Partial update. Only ``note``, ``is_favorited``, ``is_discarded`` are mutable here."""
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")
    if payload.note is not None:
        h.note = payload.note
    if payload.is_favorited is not None:
        # Match the UI rule: favoriting a discarded row is nonsense.
        if payload.is_favorited and h.is_discarded:
            raise HTTPException(
                status_code=400,
                detail="Cannot favorite a discarded highlight.",
            )
        h.is_favorited = payload.is_favorited
    if payload.is_discarded is not None:
        h.is_discarded = payload.is_discarded
        # Discarding auto-unfavorites — mirrors discard endpoint behavior.
        if h.is_discarded and h.is_favorited:
            h.is_favorited = False
    session.add(h)
    session.commit()
    session.refresh(h)
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    return _highlight_to_detail(h, book)


@router.get("/stats", response_model=StatsResponse)
def get_stats(
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> StatsResponse:
    """Aggregate counts for the authenticated user."""
    base = select(func.count(Highlight.id)).where(Highlight.user_id == token.user_id)
    total = session.exec(base).one()
    active = session.exec(
        base.where(Highlight.is_discarded == False)  # noqa: E712
    ).one()
    discarded = session.exec(
        base.where(Highlight.is_discarded == True)  # noqa: E712
    ).one()
    favorited = session.exec(
        base.where(Highlight.is_favorited == True)  # noqa: E712
    ).one()
    books_total = session.exec(
        select(func.count(func.distinct(Highlight.book_id)))
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.book_id.is_not(None))
    ).one()
    now = datetime.now(UTC).replace(tzinfo=None)
    review_due = session.exec(
        base.where(Highlight.is_discarded == False)  # noqa: E712
        .where(
            (Highlight.next_review.is_(None)) | (Highlight.next_review <= now)
        )
    ).one()
    return StatsResponse(
        highlights_total=total,
        highlights_active=active,
        highlights_discarded=discarded,
        highlights_favorited=favorited,
        books_total=books_total,
        review_due_today=review_due,
    )
