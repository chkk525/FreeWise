"""Tests for /dashboard/kindle/cookie GET + POST."""
from __future__ import annotations

import json


def _valid_state() -> bytes:
    return json.dumps({
        "cookies": [
            {"name": "at-main", "value": "x", "domain": ".amazon.com", "path": "/"},
        ],
    }).encode()


def test_get_renders_status_page(client):
    r = client.get("/dashboard/kindle/cookie")
    assert r.status_code == 200
    assert "kindle" in r.text.lower()
    assert "upload" in r.text.lower() or "storage_state" in r.text.lower()


def test_post_uploads_valid_cookie(client, tmp_path, monkeypatch):
    target = tmp_path / "storage_state.json"
    monkeypatch.setenv("KINDLE_STATE_PATH", str(tmp_path))

    r = client.post(
        "/dashboard/kindle/cookie",
        files={"file": ("storage_state.json", _valid_state(), "application/json")},
    )
    assert r.status_code == 200
    assert target.is_file()


def test_post_rejects_invalid_cookie(client, tmp_path, monkeypatch):
    monkeypatch.setenv("KINDLE_STATE_PATH", str(tmp_path))
    r = client.post(
        "/dashboard/kindle/cookie",
        files={"file": ("storage_state.json", b"not json", "application/json")},
    )
    assert r.status_code == 400
