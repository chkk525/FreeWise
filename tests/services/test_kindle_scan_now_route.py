"""Route test for POST /import/kindle/scan-now."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


def _payload() -> str:
    return json.dumps(
        {
            "schema_version": "1.0",
            "exported_at": "2026-04-25T12:00:00Z",
            "source": "kindle_notebook",
            "books": [
                {
                    "asin": "B07FCMBLM6",
                    "title": "Sapiens",
                    "author": "Yuval Noah Harari",
                    "cover_url": None,
                    "highlights": [
                        {
                            "id": "QID:h1",
                            "text": "hello world",
                            "note": None,
                            "color": "yellow",
                            "location": 1,
                            "page": None,
                            "created_at": None,
                        }
                    ],
                }
            ],
        }
    )


def test_scan_now_400_when_env_unset(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("KINDLE_IMPORTS_DIR", raising=False)
    r = client.post("/import/kindle/scan-now")
    assert r.status_code == 400
    assert "KINDLE_IMPORTS_DIR" in r.json()["detail"]


def test_scan_now_imports_pending_file(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "scrape.json").write_text(_payload())
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))

    r = client.post("/import/kindle/scan-now")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files_imported"] == 1
    assert body["books_created"] == 1
    assert body["highlights_created"] == 1
    assert (tmp_path / "processed" / "scrape.json").exists()


def test_scan_now_idempotent(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "scrape.json").write_text(_payload())
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))

    first = client.post("/import/kindle/scan-now").json()
    second = client.post("/import/kindle/scan-now").json()

    assert first["files_imported"] == 1
    assert second["files_imported"] == 0
    assert second["files_scanned"] == 0
