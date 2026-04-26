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
from datetime import date, datetime, UTC
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlmodel import Session, func, select

from app.api_v2.auth import get_api_token
from app.api_v2.schemas import (
    AuthorListItem,
    BookListItem,
    HighlightCreatePayload,
    HighlightCreateResponse,
    HighlightDetail,
    HighlightInput,
    HighlightListItem,
    HighlightUpdatePayload,
    PaginatedResponse,
    StatsResponse,
    TagAddPayload,
    TagListResponse,
    TagSummaryItem,
)
from app.db import get_session
from app.models import ApiToken, Book, Embedding, Highlight, HighlightTag, Tag
from app.routers.importer import get_or_create_book
from app.services.embeddings import (
    _env_model,
    OllamaUnavailable,
    ask_library,
    backfill_embeddings,
    top_k_similar,
)

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


def _tags_for_highlight(session: Session, highlight_id: int) -> list[str]:
    """Return tag names for one highlight in a single query.

    Excludes legacy "favorite"/"discard" pseudo-tags that the importer
    historically used as flags before the dedicated boolean columns existed.
    Sorted alphabetically so output is deterministic for tests + clients.
    """
    rows = session.exec(
        select(Tag.name)
        .join(HighlightTag, HighlightTag.tag_id == Tag.id)
        .where(HighlightTag.highlight_id == highlight_id)
    ).all()
    return sorted(
        n for n in rows
        if n and n.lower() not in ("favorite", "discard")
    )


def _highlight_to_detail(
    h: Highlight,
    book: Optional[Book],
    tags: Optional[list[str]] = None,
) -> HighlightDetail:
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
        is_mastered=getattr(h, "is_mastered", False),
        tags=tags or [],
    )


@router.get("/highlights/search", response_model=PaginatedResponse)
def search_highlights(
    q: str = Query(..., min_length=1, max_length=512),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=1000),
    include_discarded: bool = Query(default=False),
    tag: Optional[str] = Query(default=None, max_length=64),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Full-text LIKE search across this user's highlights (text + note).

    Not a Readwise endpoint — FreeWise extension under the same prefix.
    Wildcard chars in ``q`` are escaped so a ``%`` query matches a literal
    percent sign rather than every row. Optional ``tag`` filters to highlights
    that carry that exact tag (case-insensitive).
    """
    needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    pattern = f"%{needle}%"
    base = select(Highlight).where(Highlight.user_id == token.user_id).where(
        Highlight.text.like(pattern, escape="\\")
        | Highlight.note.like(pattern, escape="\\")
    )
    if not include_discarded:
        base = base.where(Highlight.is_discarded == False)  # noqa: E712

    if tag is not None and tag.strip():
        # Subquery that yields highlight_ids carrying the requested tag.
        tag_name = _normalize_tag(tag)
        tagged = (
            select(HighlightTag.highlight_id)
            .join(Tag, HighlightTag.tag_id == Tag.id)
            .where(Tag.name == tag_name)
        )
        base = base.where(Highlight.id.in_(tagged))

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

    # Bulk-load tags for all returned highlights in one query (no N+1).
    hl_ids = [h.id for h in rows]
    tags_by_hl: dict[int, list[str]] = {}
    if hl_ids:
        pairs = session.exec(
            select(HighlightTag.highlight_id, Tag.name)
            .join(Tag, HighlightTag.tag_id == Tag.id)
            .where(HighlightTag.highlight_id.in_(hl_ids))
        ).all()
        for hl_id, name in pairs:
            if name and name.lower() not in ("favorite", "discard"):
                tags_by_hl.setdefault(hl_id, []).append(name)
        for hl_id in tags_by_hl:
            tags_by_hl[hl_id].sort()

    results = [
        _highlight_to_detail(
            h,
            books_by_id.get(h.book_id) if h.book_id else None,
            tags=tags_by_hl.get(h.id, []),
        ).model_dump(mode="json")
        for h in rows
    ]
    return PaginatedResponse(count=count, results=results)


@router.get("/highlights/duplicates", response_model=PaginatedResponse)
def find_duplicates(
    prefix_chars: int = Query(default=80, ge=20, le=500,
                              description="Number of leading characters used to group."),
    min_group_size: int = Query(default=2, ge=2, le=20),
    limit: int = Query(default=50, ge=1, le=500,
                       description="Max groups returned, sorted by group size desc."),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Find probable duplicate highlights by leading-character match.

    Useful after re-importing the same Kindle book — the second import
    creates highlights with identical text but different ids. This
    endpoint groups by ``substr(text, 1, prefix_chars)`` and returns
    every group with size >= min_group_size.

    Each result is ``{prefix, count, members: [HighlightDetail, ...]}``.
    Members are sorted by id ascending so the user can keep the oldest
    and discard the rest. Discarded highlights are excluded from groups.
    """
    # GROUP BY the prefix, count members, find groups above the threshold.
    # SQLite's substr is 1-indexed; second arg is length, not end-index.
    prefix_col = func.substr(Highlight.text, 1, prefix_chars).label("prefix")
    grp_stmt = (
        select(prefix_col, func.count(Highlight.id).label("cnt"))
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(prefix_col)
        .having(func.count(Highlight.id) >= min_group_size)
        .order_by(func.count(Highlight.id).desc())
        .limit(limit)
    )
    groups = session.exec(grp_stmt).all()
    if not groups:
        return PaginatedResponse(count=0, results=[])

    # Hydrate the actual rows for each prefix in one IN-query batch.
    prefixes = [p for p, _ in groups]
    member_rows = session.exec(
        select(Highlight, prefix_col)
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(prefix_col.in_(prefixes))
        .order_by(Highlight.id.asc())
    ).all()
    members_by_prefix: dict[str, list[Highlight]] = {}
    for h, p in member_rows:
        members_by_prefix.setdefault(p, []).append(h)

    # Bulk-load the books referenced by member highlights.
    book_ids = {h.book_id for hl in members_by_prefix.values() for h in hl
                if h.book_id is not None}
    books_by_id: dict[int, Book] = {}
    if book_ids:
        for b in session.exec(select(Book).where(Book.id.in_(book_ids))).all():
            books_by_id[b.id] = b

    results: list[dict] = []
    for prefix, cnt in groups:
        members = members_by_prefix.get(prefix, [])
        results.append({
            "prefix": prefix,
            "count": int(cnt),
            "members": [
                _highlight_to_detail(
                    h, books_by_id.get(h.book_id) if h.book_id else None,
                ).model_dump(mode="json")
                for h in members
            ],
        })

    return PaginatedResponse(count=len(results), results=results)


@router.get("/highlights/today", response_model=HighlightDetail)
def highlight_of_the_day(
    salt: Optional[str] = Query(default=None, max_length=64,
                                description="Optional salt to vary the daily pick (e.g. 'morning', 'evening')."),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightDetail:
    """One stable "highlight of the day" — same row for all callers today.

    Deterministic = a daily email, a calendar widget, and the in-app
    dashboard can all show the SAME highlight today. Different from
    /random (which changes per call). Refreshes at local midnight.

    Implementation: use ``date.today()`` (server local) + total active
    highlight count to seed an index into the ordered candidate list.
    Mastered rows are *included* (mastery hides from review, not from
    serendipitous re-exposure); discarded rows are excluded.
    Optional ``salt`` varies the pick — useful for "morning/evening"
    style multiple-per-day rotations.
    """
    import hashlib

    base = (
        select(Highlight.id)
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .order_by(Highlight.id.asc())
    )
    ids = [hid for hid in session.exec(base).all()]
    if not ids:
        raise HTTPException(status_code=404, detail="No highlights to pick from.")

    seed = f"{date.today().isoformat()}:{salt or ''}".encode()
    digest = int.from_bytes(hashlib.sha256(seed).digest()[:8], "big")
    index = digest % len(ids)
    chosen_id = ids[index]

    h = session.get(Highlight, chosen_id)
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    tags = _tags_for_highlight(session, h.id)
    return _highlight_to_detail(h, book, tags=tags)


@router.get("/highlights/random", response_model=HighlightDetail)
def random_highlight(
    include_discarded: bool = Query(default=False),
    include_mastered: bool = Query(default=True),
    book_id: Optional[int] = Query(default=None),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightDetail:
    """One random highlight from the user's library.

    Useful for dashboard "highlight of the moment" widgets, daily emails,
    and "surprise me" buttons. Defaults exclude discarded but include
    mastered (mastery is just a review-queue exclusion — the highlight
    is still surface-able for serendipitous re-exposure).
    """
    stmt = select(Highlight).where(Highlight.user_id == token.user_id)
    if not include_discarded:
        stmt = stmt.where(Highlight.is_discarded == False)  # noqa: E712
    if not include_mastered:
        stmt = stmt.where(Highlight.is_mastered == False)  # noqa: E712
    if book_id is not None:
        stmt = stmt.where(Highlight.book_id == book_id)
    stmt = stmt.order_by(func.random()).limit(1)
    h = session.exec(stmt).first()
    if h is None:
        raise HTTPException(status_code=404, detail="No highlights match the filter.")
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    tags = _tags_for_highlight(session, h.id)
    return _highlight_to_detail(h, book, tags=tags)


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
    tags = _tags_for_highlight(session, h.id)
    return _highlight_to_detail(h, book, tags=tags)


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
    if payload.is_mastered is not None:
        # Mirror the HTML toggle endpoint: mastering a discarded row is
        # nonsense, but un-mastering one is allowed (lets clients fix
        # bad legacy state).
        if payload.is_mastered and h.is_discarded:
            raise HTTPException(
                status_code=400,
                detail="Cannot master a discarded highlight.",
            )
        h.is_mastered = payload.is_mastered
    session.add(h)
    session.commit()
    session.refresh(h)
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    tags = _tags_for_highlight(session, h.id)
    return _highlight_to_detail(h, book, tags=tags)


# ── Highlight-level tags ────────────────────────────────────────────────────


class _SummarizeRequest(BaseModel):
    """POST body for /api/v2/books/{id}/summarize."""

    question: Optional[str] = None  # optional override; default is "summarize"
    top_k: int = Field(default=12, ge=1, le=50)
    embed_model: Optional[str] = None
    generate_model: Optional[str] = None


@router.post("/books/{book_id}/summarize")
def summarize_book(
    book_id: int,
    payload: _SummarizeRequest,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> dict:
    """RAG: ask Ollama to summarize a book using its highlights as evidence.

    Sugar over /api/v2/ask scoped to one book_id. The default question
    asks for "key themes and ideas"; pass ``question`` to override
    (e.g. "What advice does this book give about X?").

    503 if Ollama unreachable; 404 if book is missing OR if the auth'd
    token has no highlights from this book (prevents cross-user
    enumeration via integer book id guessing).
    """
    book = session.get(Book, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    # Ownership gate: the token must own at least one highlight from
    # this book. Without this, a token can summarize any book in the
    # database by enumerating book_id.
    has_owned = session.exec(
        select(Highlight.id)
        .where(Highlight.book_id == book_id)
        .where(Highlight.user_id == token.user_id)
        .limit(1)
    ).first()
    if has_owned is None:
        raise HTTPException(status_code=404, detail="Book not found.")
    question = (payload.question or "").strip() or (
        f"Summarize the key themes and ideas from this book ('{book.title}'"
        + (f" by {book.author}" if book.author else "")
        + ") based on the highlights below. Be concise."
    )
    try:
        result = ask_library(
            session, question=question,
            top_k=max(1, min(20, payload.top_k)),
            embed_model=payload.embed_model,
            generate_model=payload.generate_model,
            book_id=book_id,
            user_id=token.user_id,
        )
    except OllamaUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama unavailable: {e}. See docs/SEMANTIC_SETUP.md.",
        ) from e
    out = result.as_dict()
    out["book_id"] = book_id
    out["book_title"] = book.title
    return out


class _AskRequest(BaseModel):
    """POST body for /api/v2/ask."""

    question: str
    # Hard cap top_k so a malicious caller can't blow up the prompt or
    # the matmul. 50 is generous; the UI tops out at 16.
    top_k: int = Field(default=8, ge=1, le=50)
    embed_model: Optional[str] = None
    generate_model: Optional[str] = None


@router.post("/ask")
def ask(
    payload: _AskRequest,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> dict:
    """RAG: retrieve top-K similar highlights to ``question``, then ask
    Ollama to compose a citation-grounded answer.

    Body: ``{"question": str, "top_k": int=8, "embed_model": str?, "generate_model": str?}``
    Response: ``{"answer", "citations": [...], "embed_model", "generate_model", "truncated"}``

    Returns 503 if Ollama isn't reachable — distinct from a generic 500
    so the CLI/MCP can show the user a setup hint instead of a stack trace.
    """
    if not payload.question or not payload.question.strip():
        raise HTTPException(status_code=400, detail="`question` is required.")
    try:
        result = ask_library(
            session, question=payload.question.strip(),
            top_k=payload.top_k,
            embed_model=payload.embed_model,
            generate_model=payload.generate_model,
            user_id=token.user_id,
        )
    except OllamaUnavailable as e:
        raise HTTPException(
            status_code=503,
            detail=f"Ollama unavailable: {e}. See docs/SEMANTIC_SETUP.md.",
        ) from e
    return result.as_dict()


class _BackfillRequest(BaseModel):
    """POST body for /api/v2/embeddings/backfill."""

    # 256 is well above the optimal Ollama batch (~64) but caps the
    # damage from a runaway caller. The CLI loops on the endpoint, so
    # large totals are still reachable across multiple calls.
    batch_size: int = Field(default=64, ge=1, le=256)
    model: Optional[str] = None


@router.post("/embeddings/backfill")
def embeddings_backfill(
    payload: _BackfillRequest,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> dict:
    """Run one batch of the embedding backfill, return a progress report.

    Designed to be called repeatedly by the CLI's loop so each batch
    commits independently. The actual loop lives in the client; this
    endpoint stays stateless. Token-gated like every /api/v2 route —
    accidental triggering by a crawler is impossible.
    """
    report = backfill_embeddings(
        session, model=payload.model, batch_size=payload.batch_size,
    )
    return report.as_dict()


@router.get("/highlights/{highlight_id}/related", response_model=PaginatedResponse)
def related_highlights(
    highlight_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    model: Optional[str] = Query(default=None, max_length=128),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Top-K semantically similar highlights to ``highlight_id``.

    Requires that embeddings have been backfilled for the chosen model
    (see ``freewise embed-backfill``). Returns ``count = 0`` and
    ``results = []`` when no embeddings exist yet — callers should
    treat that as "not yet computed" rather than "no related items".

    The source highlight itself is excluded from results. Mastered rows
    are *included* (mastery hides from review, not from semantic
    discovery). Discarded rows are excluded.
    """
    target_h = session.get(Highlight, highlight_id)
    if target_h is None or target_h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")

    model_name = model or _env_model()
    target_emb = session.exec(
        select(Embedding)
        .where(Embedding.highlight_id == highlight_id)
        .where(Embedding.model_name == model_name)
    ).first()
    if target_emb is None:
        # Coverage hole — return an empty list. The UI will surface a
        # "not yet embedded" hint based on count == 0.
        return PaginatedResponse(count=0, results=[])

    # Pull all candidate vectors for this model. For the current 25k-
    # highlight scale this is well under 100MB in RAM and the matmul
    # is sub-100ms. If we ever scale past ~250k vectors we'd switch to
    # an ANN index (sqlite-vec or hnsw).
    candidate_rows = session.exec(
        select(Embedding.highlight_id, Embedding.vector, Highlight.is_discarded)
        .join(Highlight, Highlight.id == Embedding.highlight_id)
        .where(Embedding.model_name == model_name)
        .where(Embedding.dim == target_emb.dim)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(Highlight.id != highlight_id)
        .where(Highlight.user_id == token.user_id)
    ).all()
    candidates = [(hl_id, blob) for hl_id, blob, _ in candidate_rows]
    top = top_k_similar(target_emb.vector, candidates, dim=target_emb.dim, k=limit)

    # Hydrate each top-K id back into a HighlightDetail. One IN-query
    # for the highlights, one for their books, one for their tags.
    if not top:
        return PaginatedResponse(count=0, results=[])

    ids = [hl_id for hl_id, _ in top]
    hl_rows = session.exec(select(Highlight).where(Highlight.id.in_(ids))).all()
    hl_by_id = {h.id: h for h in hl_rows}
    book_ids = {h.book_id for h in hl_rows if h.book_id is not None}
    books_by_id: dict[int, Book] = {}
    if book_ids:
        books = session.exec(select(Book).where(Book.id.in_(book_ids))).all()
        books_by_id = {b.id: b for b in books}
    tag_pairs = session.exec(
        select(HighlightTag.highlight_id, Tag.name)
        .join(Tag, HighlightTag.tag_id == Tag.id)
        .where(HighlightTag.highlight_id.in_(ids))
    ).all()
    tags_by_hl: dict[int, list[str]] = {}
    for hl_id, name in tag_pairs:
        if name and name.lower() not in ("favorite", "discard"):
            tags_by_hl.setdefault(hl_id, []).append(name)
    for k in tags_by_hl:
        tags_by_hl[k].sort()

    results: list[dict] = []
    for hl_id, score in top:
        h = hl_by_id.get(hl_id)
        if h is None:
            continue
        detail = _highlight_to_detail(
            h,
            books_by_id.get(h.book_id) if h.book_id else None,
            tags=tags_by_hl.get(h.id, []),
        ).model_dump(mode="json")
        # Surface the similarity score so clients can choose to display
        # or threshold-filter. Rounded for readable JSON.
        detail["similarity"] = round(score, 4)
        results.append(detail)

    return PaginatedResponse(count=len(results), results=results)


class _AppendNotePayload(BaseModel):
    text: str = Field(..., min_length=1, max_length=8191)


@router.post("/highlights/{highlight_id}/note/append", response_model=HighlightDetail)
def append_highlight_note(
    highlight_id: int,
    payload: _AppendNotePayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> HighlightDetail:
    """Append ``text`` to the highlight's existing note.

    Distinct from PATCH note=... which REPLACES. This endpoint preserves
    the existing note and adds a blank-line separator + ``text`` underneath.
    Useful when adding a follow-up thought during review without losing
    the original note. 404 on missing or other-user highlight.
    """
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")
    extra = payload.text.strip()
    if not extra:
        raise HTTPException(status_code=400, detail="text cannot be empty.")
    combined = f"{h.note.rstrip()}\n\n{extra}" if h.note else extra
    # Enforce the same 8191-char cap that applies to a single SET. An
    # 8000-char existing note + 8000-char append would otherwise silently
    # store a 16000-char note (SQLite TEXT has no hard limit) and break
    # any client that assumes the documented cap holds.
    if len(combined) > 8191:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Combined note would be {len(combined)} chars; "
                "max is 8191. Edit the existing note instead."
            ),
        )
    h.note = combined
    session.add(h)
    session.commit()
    session.refresh(h)
    book = session.get(Book, h.book_id) if h.book_id is not None else None
    return _highlight_to_detail(h, book, tags=_tags_for_highlight(session, h.id))


@router.get("/highlights/{highlight_id}/tags", response_model=TagListResponse)
def list_highlight_tags(
    highlight_id: int,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> TagListResponse:
    """List tags attached to one highlight."""
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")
    return TagListResponse(tags=_tags_for_highlight(session, h.id))


def _normalize_tag(name: str) -> str:
    """Lowercase + collapse whitespace. Tags are case-insensitive on lookup."""
    return " ".join(name.strip().split()).lower()


@router.post(
    "/highlights/{highlight_id}/tags",
    response_model=TagListResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_highlight_tag(
    highlight_id: int,
    payload: TagAddPayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> TagListResponse:
    """Attach a tag to a highlight. Idempotent — re-attaching a tag is a no-op
    rather than a 4xx, so callers don't need to know whether the link existed."""
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")

    name = _normalize_tag(payload.name)
    if not name:
        raise HTTPException(status_code=400, detail="Tag name cannot be empty.")
    if name in ("favorite", "discard"):
        # These are legacy pseudo-tags reserved by the importer for boolean
        # flag semantics. Use is_favorited / is_discarded fields instead.
        raise HTTPException(
            status_code=400,
            detail="Tag names 'favorite' and 'discard' are reserved.",
        )

    tag = session.exec(select(Tag).where(Tag.name == name)).first()
    if tag is None:
        tag = Tag(name=name)
        session.add(tag); session.commit(); session.refresh(tag)

    existing = session.exec(
        select(HighlightTag)
        .where(HighlightTag.highlight_id == h.id)
        .where(HighlightTag.tag_id == tag.id)
    ).first()
    if existing is None:
        session.add(HighlightTag(highlight_id=h.id, tag_id=tag.id))
        session.commit()

    return TagListResponse(tags=_tags_for_highlight(session, h.id))


@router.delete(
    "/highlights/{highlight_id}/tags/{tag_name}",
    response_model=TagListResponse,
)
def remove_highlight_tag(
    highlight_id: int,
    tag_name: str,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> TagListResponse:
    """Remove a tag from a highlight. Idempotent — removing a non-existent
    link returns the current tag list with no error."""
    h = session.get(Highlight, highlight_id)
    if h is None or h.user_id != token.user_id:
        raise HTTPException(status_code=404, detail="Highlight not found.")

    name = _normalize_tag(tag_name)
    tag = session.exec(select(Tag).where(Tag.name == name)).first()
    if tag is not None:
        link = session.exec(
            select(HighlightTag)
            .where(HighlightTag.highlight_id == h.id)
            .where(HighlightTag.tag_id == tag.id)
        ).first()
        if link is not None:
            session.delete(link)
            session.commit()

    return TagListResponse(tags=_tags_for_highlight(session, h.id))


@router.get("/authors", response_model=PaginatedResponse)
def list_authors(
    q: Optional[str] = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Distinct authors with book + highlight counts.

    Sorted by highlight_count descending so the heaviest-quoted authors
    surface first. Optional ``q`` does a case-insensitive substring match
    on the author name (LIKE-escaped). Excludes books with NULL author.
    """
    base = (
        select(
            Book.author,
            func.count(func.distinct(Book.id)).label("book_count"),
            func.count(Highlight.id).label("highlight_count"),
        )
        .join(Highlight, Highlight.book_id == Book.id)
        .where(Book.author.is_not(None))
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(Book.author)
    )

    if q:
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        base = base.where(Book.author.like(f"%{needle}%", escape="\\"))

    # Count distinct authors via a subquery over the grouped result.
    count_q = select(func.count()).select_from(base.subquery())
    total = session.exec(count_q).one()

    rows = session.exec(
        base.order_by(func.count(Highlight.id).desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    results = [
        AuthorListItem(
            name=name, book_count=int(book_count), highlight_count=int(hl_count),
        ).model_dump(mode="json")
        for name, book_count, hl_count in rows
    ]
    return PaginatedResponse(count=total, results=results)


class _TagRenamePayload(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=64)


@router.post("/tags/{name}/rename", response_model=TagSummaryItem)
def rename_tag(
    name: str,
    payload: _TagRenamePayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> TagSummaryItem:
    """Rename a tag globally. The new name is normalized (lowercase +
    collapsed whitespace) and may not collide with another existing tag
    or with the reserved names favorite/discard.

    Returns the (possibly new) tag's summary row. 404 if the tag doesn't
    exist; 409 if renaming would collide with an existing tag (use the
    /merge endpoint instead).
    """
    src_name = _normalize_tag(name)
    dst_name = _normalize_tag(payload.new_name)
    if not dst_name:
        raise HTTPException(status_code=400, detail="`new_name` cannot be empty.")
    if dst_name in ("favorite", "discard"):
        raise HTTPException(status_code=400, detail="`new_name` is reserved.")
    if src_name == dst_name:
        # No-op rename — return the current summary.
        pass

    src = session.exec(select(Tag).where(Tag.name == src_name)).first()
    if src is None:
        raise HTTPException(status_code=404, detail="Tag not found.")

    if src_name != dst_name:
        existing_dst = session.exec(select(Tag).where(Tag.name == dst_name)).first()
        if existing_dst is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Tag '{dst_name}' already exists — "
                    f"use POST /tags/{src_name}/merge to combine them."
                ),
            )
        src.name = dst_name
        session.add(src)
        session.commit()

    cnt = session.exec(
        select(func.count(HighlightTag.tag_id))
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(HighlightTag.tag_id == src.id)
        .where(Highlight.is_discarded == False)  # noqa: E712
    ).one() or 0
    return TagSummaryItem(name=dst_name, highlight_count=int(cnt))


class _TagMergePayload(BaseModel):
    into: str = Field(..., min_length=1, max_length=64)


@router.post("/tags/{name}/merge", response_model=TagSummaryItem)
def merge_tag(
    name: str,
    payload: _TagMergePayload,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> TagSummaryItem:
    """Merge tag ``name`` into ``into``. All HighlightTag links are moved
    to the destination tag (skipping rows that already had ``into``);
    the source Tag row is then deleted.

    404 if either tag doesn't exist; 400 if names match or destination
    is reserved.
    """
    src_name = _normalize_tag(name)
    dst_name = _normalize_tag(payload.into)
    if not src_name or not dst_name:
        raise HTTPException(status_code=400, detail="Both names required.")
    if src_name == dst_name:
        raise HTTPException(status_code=400, detail="Cannot merge a tag into itself.")
    if dst_name in ("favorite", "discard"):
        raise HTTPException(status_code=400, detail="`into` is reserved.")

    src = session.exec(select(Tag).where(Tag.name == src_name)).first()
    dst = session.exec(select(Tag).where(Tag.name == dst_name)).first()
    if src is None or dst is None:
        raise HTTPException(status_code=404, detail="Source or destination tag not found.")

    # Move every highlight that has the src tag to also have the dst tag,
    # unless it already does. Then delete src links + the src Tag row.
    src_links = session.exec(
        select(HighlightTag).where(HighlightTag.tag_id == src.id)
    ).all()
    dst_links_existing = {
        l.highlight_id for l in session.exec(
            select(HighlightTag).where(HighlightTag.tag_id == dst.id)
        ).all()
    }
    for link in src_links:
        if link.highlight_id not in dst_links_existing:
            session.add(HighlightTag(highlight_id=link.highlight_id, tag_id=dst.id))
        session.delete(link)
    session.delete(src)
    session.commit()

    cnt = session.exec(
        select(func.count(HighlightTag.tag_id))
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(HighlightTag.tag_id == dst.id)
        .where(Highlight.is_discarded == False)  # noqa: E712
    ).one() or 0
    return TagSummaryItem(name=dst_name, highlight_count=int(cnt))


class _AuthorRenamePayload(BaseModel):
    new_name: str = Field(..., min_length=1, max_length=512)


@router.post("/authors/rename", response_model=AuthorListItem)
def rename_author(
    payload: _AuthorRenamePayload,
    name: str = Query(..., max_length=512),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> AuthorListItem:
    """Rename an author across every book. Use ``?name=Old Name`` so
    URL-encoded names with slashes / special chars round-trip safely
    (path params would force escaping).

    Returns the new author's summary row. 404 if no books matched.
    """
    src = (name or "").strip()
    dst = (payload.new_name or "").strip()
    if not src or not dst:
        raise HTTPException(status_code=400, detail="Both names required.")
    if src == dst:
        # No-op rename.
        pass

    rows = session.exec(select(Book).where(Book.author == src)).all()
    if not rows:
        raise HTTPException(status_code=404, detail=f"No books with author={src!r}.")

    changed = 0
    if src != dst:
        for b in rows:
            b.author = dst
            session.add(b)
            changed += 1
        session.commit()

    # Recompute summary for the new author.
    book_count = session.exec(
        select(func.count(func.distinct(Book.id)))
        .where(Book.author == dst)
    ).one() or 0
    hl_count = session.exec(
        select(func.count(Highlight.id))
        .join(Book, Book.id == Highlight.book_id)
        .where(Book.author == dst)
        .where(Highlight.is_discarded == False)  # noqa: E712
    ).one() or 0
    return AuthorListItem(name=dst, book_count=int(book_count), highlight_count=int(hl_count))


@router.get("/tags", response_model=PaginatedResponse)
def list_tags(
    q: Optional[str] = Query(default=None, max_length=128),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> PaginatedResponse:
    """Distinct highlight-level tags with usage counts.

    Excludes the legacy "favorite"/"discard" pseudo-tags and counts only
    tags attached to non-discarded highlights belonging to the auth'd
    user. Sorted by highlight_count desc so heavy-use tags surface first.
    Optional ``q`` substring-filters on tag name (LIKE-escaped).
    """
    base = (
        select(Tag.name, func.count(HighlightTag.tag_id).label("hl_count"))
        .join(HighlightTag, HighlightTag.tag_id == Tag.id)
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(func.lower(Tag.name).notin_(("favorite", "discard")))
        .group_by(Tag.name)
    )

    if q:
        needle = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        base = base.where(Tag.name.like(f"%{needle}%", escape="\\"))

    count_q = select(func.count()).select_from(base.subquery())
    total = session.exec(count_q).one()

    rows = session.exec(
        base.order_by(func.count(HighlightTag.tag_id).desc(), Tag.name.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()

    results = [
        TagSummaryItem(name=name, highlight_count=int(cnt)).model_dump(mode="json")
        for name, cnt in rows
    ]
    return PaginatedResponse(count=total, results=results)


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
    mastered = session.exec(
        base.where(Highlight.is_mastered == True)  # noqa: E712
    ).one()
    books_total = session.exec(
        select(func.count(func.distinct(Highlight.book_id)))
        .where(Highlight.user_id == token.user_id)
        .where(Highlight.book_id.is_not(None))
    ).one()
    now = datetime.now(UTC).replace(tzinfo=None)
    review_due = session.exec(
        base.where(Highlight.is_discarded == False)  # noqa: E712
        # Mirror the review queue's filter: mastered rows aren't due.
        .where(Highlight.is_mastered == False)  # noqa: E712
        .where(
            (Highlight.next_review.is_(None)) | (Highlight.next_review <= now)
        )
    ).one()
    return StatsResponse(
        highlights_total=total,
        highlights_active=active,
        highlights_discarded=discarded,
        highlights_favorited=favorited,
        highlights_mastered=mastered,
        books_total=books_total,
        review_due_today=review_due,
    )
