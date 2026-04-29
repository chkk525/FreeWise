"""Frozen dataclasses for the Kindle Notebook export JSON contract.

The shape mirrors ``docs/KINDLE_JSON_SCHEMA.md`` exactly. Tuples are used
instead of lists so that instances are deeply immutable (lesson from
common/coding-style.md: never mutate, always rebuild).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from typing import Any, Iterable

SCHEMA_VERSION: str = "1.0"
SOURCE_NAME: str = "kindle_notebook"
HIGHLIGHT_COLORS: frozenset[str] = frozenset({"yellow", "blue", "pink", "orange"})


@dataclass(frozen=True, slots=True)
class KindleHighlight:
    """A single highlight (and optional note) inside a book.

    All optional fields default to ``None`` so the scraper can populate
    only what it actually parsed. ``created_at`` is reserved but always
    ``None`` in v1 — Kindle does not expose timestamps via kp/notebook.
    """

    id: str
    text: str
    note: str | None = None
    color: str | None = None
    location: int | None = None
    page: int | None = None
    created_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KindleHighlight":
        return cls(
            id=str(data["id"]),
            text=str(data["text"]),
            note=_optional_str(data.get("note")),
            color=_optional_str(data.get("color")),
            location=_optional_int(data.get("location")),
            page=_optional_int(data.get("page")),
            created_at=_optional_str(data.get("created_at")),
        )


@dataclass(frozen=True, slots=True)
class KindleBook:
    """A book in the user's Kindle library, with zero or more highlights."""

    asin: str
    title: str
    author: str | None = None
    cover_url: str | None = None
    highlights: tuple[KindleHighlight, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "asin": self.asin,
            "title": self.title,
            "author": self.author,
            "cover_url": self.cover_url,
            "highlights": [h.to_dict() for h in self.highlights],
        }

    def with_highlights(self, highlights: Iterable[KindleHighlight]) -> "KindleBook":
        """Return a copy of this book with replaced highlights (immutable update)."""

        return replace(self, highlights=tuple(highlights))

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KindleBook":
        raw_highlights = data.get("highlights") or ()
        return cls(
            asin=str(data["asin"]),
            title=str(data["title"]),
            author=_optional_str(data.get("author")),
            cover_url=_optional_str(data.get("cover_url")),
            highlights=tuple(KindleHighlight.from_dict(h) for h in raw_highlights),
        )


@dataclass(frozen=True, slots=True)
class ScrapeOutput:
    """Top-level export payload.

    Always carries ``schema_version`` and ``source`` so the importer can
    reject incompatible files early.
    """

    schema_version: str
    exported_at: str
    source: str
    books: tuple[KindleBook, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "exported_at": self.exported_at,
            "source": self.source,
            "books": [b.to_dict() for b in self.books],
        }

    def to_json(self, *, indent: int = 2) -> str:
        # ensure_ascii=False so highlights with non-ASCII text (Japanese books,
        # smart quotes, em-dashes, ...) round-trip cleanly through the importer.
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScrapeOutput":
        raw_books = data.get("books") or ()
        return cls(
            schema_version=str(data["schema_version"]),
            exported_at=str(data["exported_at"]),
            source=str(data["source"]),
            books=tuple(KindleBook.from_dict(b) for b in raw_books),
        )


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
