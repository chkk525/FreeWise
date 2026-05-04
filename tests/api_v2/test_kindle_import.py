"""Tests for POST /api/v2/imports/kindle (browser-extension entry point)."""
from __future__ import annotations

import gzip
import io
import json

import pytest


def _envelope(books=None):
    return {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": books or [],
    }


def test_post_requires_token(client):
    r = client.post("/api/v2/imports/kindle", json=_envelope())
    assert r.status_code == 401


def test_post_rejects_unknown_token(client):
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token totally-bogus-value"},
    )
    assert r.status_code == 401


def test_post_accepts_valid_envelope(client, valid_token):
    body = _envelope(books=[
        {
            "asin": "B07TEST",
            "title": "Test Book",
            "author": "Test Author",
            "cover_url": None,
            "highlights": [
                {"id": "QID:1", "text": "first highlight", "note": None,
                 "color": "yellow", "location": 100, "page": None,
                 "created_at": None}
            ],
        }
    ])
    r = client.post(
        "/api/v2/imports/kindle",
        json=body,
        headers={"Authorization": f"Token {valid_token}"},
    )
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["books_created"] == 1
    assert payload["highlights_created"] == 1
    assert payload["errors"] == []


def test_post_rejects_invalid_schema(client, valid_token):
    bad = {"schema_version": "1.0", "source": "kindle_notebook"}  # missing fields
    r = client.post(
        "/api/v2/imports/kindle",
        json=bad,
        headers={"Authorization": f"Token {valid_token}"},
    )
    assert r.status_code == 400
    assert "schema" in r.json()["detail"].lower() or "books" in r.json()["detail"].lower()


def test_post_accepts_gzipped_body(client, valid_token):
    body = _envelope(books=[
        {"asin": "B07GZ", "title": "Compressed", "highlights": [
            {"id": "QID:1", "text": "gz highlight"}
        ]}
    ])
    raw = json.dumps(body).encode("utf-8")
    compressed = gzip.compress(raw)
    r = client.post(
        "/api/v2/imports/kindle",
        content=compressed,
        headers={
            "Authorization": f"Token {valid_token}",
            "Content-Type": "application/json",
            "Content-Encoding": "gzip",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["books_created"] == 1
