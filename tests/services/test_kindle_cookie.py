"""Unit tests for the storage_state.json validation + atomic write service."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.services.kindle_cookie import (
    CookieValidationError,
    ScrapeRunningError,
    write_storage_state,
    read_storage_state_status,
)


def _valid_storage_state() -> dict:
    return {
        "cookies": [
            {"name": "at-main", "value": "x", "domain": ".amazon.com", "path": "/"},
            {"name": "session-token", "value": "y", "domain": ".amazon.com", "path": "/"},
        ],
        "origins": [],
    }


def test_write_creates_file_atomically(tmp_path):
    target = tmp_path / "storage_state.json"
    write_storage_state(json.dumps(_valid_storage_state()).encode(), target_path=target)
    assert target.is_file()
    assert json.loads(target.read_text())["cookies"][0]["name"] == "at-main"


def test_write_rejects_invalid_json(tmp_path):
    with pytest.raises(CookieValidationError, match="JSON"):
        write_storage_state(b"not json at all", target_path=tmp_path / "x.json")


def test_write_rejects_missing_cookies_array(tmp_path):
    with pytest.raises(CookieValidationError, match="cookies"):
        write_storage_state(b'{"origins": []}', target_path=tmp_path / "x.json")


def test_write_rejects_missing_amazon_cookie(tmp_path):
    bad = {
        "cookies": [
            {"name": "random", "value": "x", "domain": ".example.com", "path": "/"}
        ]
    }
    with pytest.raises(CookieValidationError, match="amazon"):
        write_storage_state(
            json.dumps(bad).encode(),
            target_path=tmp_path / "x.json",
        )


def test_write_rejects_size_over_100kb(tmp_path):
    huge = b"x" * 101_000
    with pytest.raises(CookieValidationError, match="size"):
        write_storage_state(huge, target_path=tmp_path / "x.json")


def test_write_returns_409_when_scrape_running(tmp_path, monkeypatch):
    state_file = tmp_path / "scrape_state.json"
    state_file.write_text(json.dumps({"pid": 1, "finished_at": None}))
    monkeypatch.setenv("KINDLE_SCRAPE_STATE_FILE", str(state_file))

    with pytest.raises(ScrapeRunningError):
        write_storage_state(
            json.dumps(_valid_storage_state()).encode(),
            target_path=tmp_path / "x.json",
        )


def test_status_reads_existing_file(tmp_path):
    p = tmp_path / "storage_state.json"
    p.write_text(json.dumps(_valid_storage_state()))
    s = read_storage_state_status(p)
    assert s["exists"] is True
    assert s["has_at_main"] is True
    assert ".amazon.com" in s["domains"]


def test_status_handles_missing_file(tmp_path):
    s = read_storage_state_status(tmp_path / "does-not-exist.json")
    assert s["exists"] is False
