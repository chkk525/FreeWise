"""Unit tests for the Kindle Notebook dataclasses.

These cover:
- frozen-ness (mutation should raise)
- equality based on field values
- ``to_dict`` / ``from_dict`` round-trip
- ``to_json`` parses to the same structure as ``to_dict``
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from scrapers.kindle.models import (
    SCHEMA_VERSION,
    SOURCE_NAME,
    KindleBook,
    KindleHighlight,
    ScrapeOutput,
)


def _sample_highlight() -> KindleHighlight:
    return KindleHighlight(
        id="QID:h1",
        text="Hello.",
        note=None,
        color="yellow",
        location=42,
        page=None,
        created_at=None,
    )


def _sample_book() -> KindleBook:
    return KindleBook(
        asin="B000TEST",
        title="A Test Book",
        author="Author X",
        cover_url=None,
        highlights=(_sample_highlight(),),
    )


def _sample_output() -> ScrapeOutput:
    return ScrapeOutput(
        schema_version=SCHEMA_VERSION,
        exported_at="2026-04-25T12:34:56+00:00",
        source=SOURCE_NAME,
        books=(_sample_book(),),
    )


class TestFrozenness:
    def test_highlight_is_frozen(self) -> None:
        h = _sample_highlight()
        with pytest.raises(dataclasses.FrozenInstanceError):
            h.text = "mutated"  # type: ignore[misc]

    def test_book_is_frozen(self) -> None:
        b = _sample_book()
        with pytest.raises(dataclasses.FrozenInstanceError):
            b.title = "mutated"  # type: ignore[misc]

    def test_scrape_output_is_frozen(self) -> None:
        o = _sample_output()
        with pytest.raises(dataclasses.FrozenInstanceError):
            o.source = "other"  # type: ignore[misc]


class TestEquality:
    def test_two_highlights_with_same_fields_are_equal(self) -> None:
        assert _sample_highlight() == _sample_highlight()

    def test_two_books_with_same_fields_are_equal(self) -> None:
        assert _sample_book() == _sample_book()


class TestRoundTrip:
    def test_highlight_round_trip(self) -> None:
        h = _sample_highlight()
        assert KindleHighlight.from_dict(h.to_dict()) == h

    def test_book_round_trip(self) -> None:
        b = _sample_book()
        assert KindleBook.from_dict(b.to_dict()) == b

    def test_scrape_output_round_trip_via_to_dict(self) -> None:
        o = _sample_output()
        assert ScrapeOutput.from_dict(o.to_dict()) == o

    def test_scrape_output_round_trip_via_json(self) -> None:
        o = _sample_output()
        rebuilt = ScrapeOutput.from_dict(json.loads(o.to_json()))
        assert rebuilt == o


class TestImmutableUpdate:
    def test_with_highlights_returns_new_book(self) -> None:
        book = _sample_book()
        new = book.with_highlights(())
        assert new is not book
        assert book.highlights == (_sample_highlight(),)
        assert new.highlights == ()


class TestSchemaConstants:
    def test_schema_version_is_one_dot_zero(self) -> None:
        assert SCHEMA_VERSION == "1.0"

    def test_source_name_matches_contract(self) -> None:
        assert SOURCE_NAME == "kindle_notebook"
