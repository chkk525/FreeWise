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
