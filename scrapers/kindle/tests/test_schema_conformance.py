"""Schema conformance tests.

The fixture under ``scrapers/kindle/fixtures/kindle_notebook_sample.json`` is
the canonical contract document. The scraper output MUST round-trip through
our dataclasses without any structural drift, otherwise the importer in
``app/importers/kindle_notebook.py`` (separate repo) will reject the file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scrapers.kindle.models import SCHEMA_VERSION, SOURCE_NAME, ScrapeOutput

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1] / "fixtures" / "kindle_notebook_sample.json"
)


@pytest.fixture(scope="module")
def fixture_dict() -> dict:
    with FIXTURE_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def test_fixture_exists() -> None:
    assert FIXTURE_PATH.exists(), f"Missing fixture: {FIXTURE_PATH}"


def test_fixture_parses_into_scrape_output(fixture_dict: dict) -> None:
    scrape = ScrapeOutput.from_dict(fixture_dict)
    assert scrape.schema_version == SCHEMA_VERSION
    assert scrape.source == SOURCE_NAME
    assert scrape.exported_at == fixture_dict["exported_at"]
    assert len(scrape.books) == len(fixture_dict["books"])


def test_round_trip_preserves_structure(fixture_dict: dict) -> None:
    scrape = ScrapeOutput.from_dict(fixture_dict)
    re_serialized = json.loads(scrape.to_json())
    assert re_serialized == fixture_dict


def test_book_with_no_highlights_is_supported(fixture_dict: dict) -> None:
    scrape = ScrapeOutput.from_dict(fixture_dict)
    empty_books = [b for b in scrape.books if len(b.highlights) == 0]
    assert len(empty_books) >= 1, (
        "Fixture must contain at least one book with no highlights "
        "to lock in that the schema allows it."
    )


def test_known_books_present(fixture_dict: dict) -> None:
    scrape = ScrapeOutput.from_dict(fixture_dict)
    asins = {b.asin for b in scrape.books}
    # These three ASINs are part of the contract fixture; if they ever change
    # in the fixture, the scraper team and the importer team need to know.
    assert {"B07FCMBLM6", "B00KQYTBNW", "B0BOOK3EMPTY"}.issubset(asins)


def test_highlight_color_values_are_in_allowed_set(fixture_dict: dict) -> None:
    scrape = ScrapeOutput.from_dict(fixture_dict)
    allowed = {"yellow", "blue", "pink", "orange", None}
    for book in scrape.books:
        for h in book.highlights:
            assert h.color in allowed, f"unexpected color {h.color!r}"


def test_created_at_is_always_null_in_v1(fixture_dict: dict) -> None:
    """Schema doc says: 'Always null in v1.' Lock this in."""

    scrape = ScrapeOutput.from_dict(fixture_dict)
    for book in scrape.books:
        for h in book.highlights:
            assert h.created_at is None
