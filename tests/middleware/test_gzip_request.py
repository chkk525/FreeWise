"""Middleware that decompresses Content-Encoding: gzip request bodies."""
from __future__ import annotations

import gzip
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.gzip_request import GzipRequestMiddleware


def _build_app() -> TestClient:
    app = FastAPI()
    app.add_middleware(GzipRequestMiddleware)

    @app.post("/echo")
    async def echo(payload: dict) -> dict:
        return payload

    return TestClient(app)


def test_uncompressed_body_passthrough():
    client = _build_app()
    r = client.post("/echo", json={"hello": "world"})
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_gzipped_body_decompressed():
    client = _build_app()
    raw = json.dumps({"hello": "world"}).encode()
    compressed = gzip.compress(raw)
    r = client.post(
        "/echo",
        content=compressed,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 200
    assert r.json() == {"hello": "world"}


def test_gzipped_body_with_invalid_compression_returns_400():
    client = _build_app()
    r = client.post(
        "/echo",
        content=b"not actually gzip",
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 400


def test_oversized_compressed_body_returns_413(monkeypatch):
    """Adversarially-large compressed body is rejected before decompression."""
    from app.middleware import gzip_request as mod

    monkeypatch.setattr(mod, "MAX_COMPRESSED_BYTES", 100)
    client = _build_app()
    # Random non-compressible data so the compressed payload genuinely
    # exceeds the 100-byte cap (zeros gzip down to 40 bytes regardless
    # of length).
    import secrets

    big = gzip.compress(secrets.token_bytes(2000))
    assert len(big) > 100
    r = client.post(
        "/echo",
        content=big,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 413
    assert "Compressed body exceeds" in r.json()["detail"]


def test_gzip_bomb_decompression_is_capped(monkeypatch):
    """A small compressed payload that expands past the decompression cap is
    rejected with 413, NOT silently allowed to OOM the worker."""
    from app.middleware import gzip_request as mod

    # Force a low decompression ceiling so the test runs in milliseconds.
    monkeypatch.setattr(mod, "MAX_DECOMPRESSED_BYTES", 10_000)

    # 1 MB of zeros gzips down to ~1 KB but expands past the 10 KB cap.
    bomb = gzip.compress(b"\x00" * 1_000_000)
    assert len(bomb) < 10_000  # compressed payload itself fits
    client = _build_app()
    r = client.post(
        "/echo",
        content=bomb,
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert r.status_code == 413
    assert "Decompressed body exceeds" in r.json()["detail"]
