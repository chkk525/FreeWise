"""Pydantic request / response models for the Readwise-compatible v2 API.

Field names match Readwise's public wire format (see https://readwise.io/api_deets)
so existing integrations work unchanged. The response shape, on the other hand,
is intentionally simpler than Readwise's: we return the minimum fields the
Chrome extension and any reasonable consumer need, and document the gaps in
``docs`` and route docstrings.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class HighlightInput(BaseModel):
    """One element of the ``highlights`` array in a POST /api/v2/highlights/ body."""

    model_config = ConfigDict(str_strip_whitespace=True)

    text: str = Field(..., min_length=1, max_length=8191)
    title: Optional[str] = Field(default=None, max_length=511)
    author: Optional[str] = Field(default=None, max_length=1024)
    image_url: Optional[str] = Field(default=None, max_length=2047)
    source_url: Optional[str] = Field(default=None, max_length=2047)
    source_type: Optional[str] = Field(default=None, max_length=64)
    category: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=8191)
    location: Optional[int] = None
    location_type: Optional[str] = Field(default=None, max_length=32)
    highlighted_at: Optional[datetime] = None
    # Accepted but currently ignored — Readwise uses this to round-trip
    # extension-generated permalinks; we don't yet persist them.
    highlight_url: Optional[str] = Field(default=None, max_length=4095)


class HighlightCreatePayload(BaseModel):
    """POST /api/v2/highlights/ body."""

    highlights: List[HighlightInput] = Field(default_factory=list)


class HighlightCreateResponse(BaseModel):
    """Result of POST /api/v2/highlights/."""

    created: int
    skipped_duplicates: int
    errors: List[str] = Field(default_factory=list)


class HighlightListItem(BaseModel):
    id: int
    text: str
    title: Optional[str] = None
    author: Optional[str] = None
    note: Optional[str] = None
    location: Optional[int] = None
    location_type: Optional[str] = None
    highlighted_at: Optional[datetime] = None
    book_id: Optional[int] = None


class BookListItem(BaseModel):
    id: int
    title: str
    author: Optional[str] = None
    num_highlights: int
    cover_image_url: Optional[str] = None


class PaginatedResponse(BaseModel):
    """Mirror Readwise's pagination envelope (``count``/``next``/``previous``)."""

    count: int
    next: Optional[str] = None
    previous: Optional[str] = None
    results: List[dict] = Field(default_factory=list)


class HighlightDetail(BaseModel):
    """Single highlight, returned by ``GET /api/v2/highlights/{id}``."""

    id: int
    text: str
    title: Optional[str] = None
    author: Optional[str] = None
    note: Optional[str] = None
    location: Optional[int] = None
    location_type: Optional[str] = None
    highlighted_at: Optional[datetime] = None
    book_id: Optional[int] = None
    is_favorited: bool = False
    is_discarded: bool = False
    is_mastered: bool = False
    tags: List[str] = Field(default_factory=list)


class TagAddPayload(BaseModel):
    """Body for ``POST /api/v2/highlights/{id}/tags`` — single tag string."""

    name: str = Field(..., min_length=1, max_length=64)


class TagListResponse(BaseModel):
    """Body for ``GET /api/v2/highlights/{id}/tags``."""

    tags: List[str]


class HighlightUpdatePayload(BaseModel):
    """Partial update body for ``PATCH /api/v2/highlights/{id}``."""

    note: Optional[str] = None
    is_favorited: Optional[bool] = None
    is_discarded: Optional[bool] = None
    is_mastered: Optional[bool] = None


class AuthorListItem(BaseModel):
    name: str
    book_count: int
    highlight_count: int


class StatsResponse(BaseModel):
    """Counts + streak summary for ``GET /api/v2/stats``."""

    highlights_total: int
    highlights_active: int
    highlights_discarded: int
    highlights_favorited: int
    highlights_mastered: int
    books_total: int
    review_due_today: int
