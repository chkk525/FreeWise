"""Verify scraper loads its selector list from the shared JSON file."""
from __future__ import annotations

import json
from pathlib import Path

from scrapers.kindle import scraper


REPO_ROOT = Path(__file__).resolve().parents[3]
SHARED_JSON = REPO_ROOT / "shared" / "kindle-selectors.json"


def test_scraper_uses_shared_library_container_selectors():
    expected = json.loads(SHARED_JSON.read_text())["library_container"]
    assert tuple(scraper.LIBRARY_CONTAINER_SELECTORS) == tuple(expected)


def test_scraper_uses_shared_library_row_selector():
    expected = json.loads(SHARED_JSON.read_text())["library_row"]
    assert scraper.LIBRARY_ROW_SELECTOR == expected


def test_scraper_uses_shared_notebook_url():
    expected = json.loads(SHARED_JSON.read_text())["notebook_url"]
    assert scraper.NOTEBOOK_URL == expected
