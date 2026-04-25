"""Dashboard integration tests for the Kindle import card and JSON endpoint.

The dashboard's full HTML rendering path (`/dashboard/ui`) is broken in the
Python 3.14 baseline due to a Jinja2 LRU-cache key compatibility issue (the
"pre-existing starlette failures" mentioned in the task). We work around that
by rendering the template directly through Jinja2's filesystem environment,
which exercises the same template code without going through Starlette's
broken cache key path.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.kindle_import_status import get_status


def _stub_request() -> SimpleNamespace:
    """Minimal Request-like object satisfying base.html's `request.state.*` access."""
    return SimpleNamespace(
        state=SimpleNamespace(streak=0, theme="light"),
        url=SimpleNamespace(path="/dashboard/ui"),
    )


def _render_dashboard(**overrides) -> str:
    """Render dashboard.html via a fresh Jinja env (bypasses broken Starlette cache)."""
    env = Environment(
        loader=FileSystemLoader("app/templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("dashboard.html")
    base_ctx = {
        "request": _stub_request(),
        "settings": None,
        "daily_review_count": 5,
        "reviewed_today": False,
        "highlights_reviewed_count": 0,
        "total_books": 0,
        "total_highlights": 0,
        "active_highlights": 0,
        "total_favorited": 0,
        "total_discarded": 0,
        "favorited_percentage": 0,
        "discarded_percentage": 0,
        "active_percentage": 0,
        "heatmap_data": {},
        "review_heatmap_data": {},
        "current_streak": 0,
        "longest_streak": 0,
    }
    base_ctx.update(overrides)
    return template.render(**base_ctx)


def test_kindle_status_endpoint_returns_json(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))

    resp = client.get("/dashboard/kindle/status")

    assert resp.status_code == 200
    body = resp.json()
    expected_keys = {
        "enabled",
        "imports_dir",
        "last_imported_at",
        "last_imported_filename",
        "last_imported_books",
        "last_imported_highlights",
        "pending_files",
        "processed_files",
        "total_kindle_books",
        "total_kindle_highlights",
    }
    assert expected_keys.issubset(body.keys())
    assert body["enabled"] is True
    assert body["imports_dir"] == str(tmp_path)
    assert body["pending_files"] == 0
    assert body["processed_files"] == 0


def test_dashboard_renders_kindle_card_when_enabled(
    db, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KINDLE_IMPORTS_DIR", str(tmp_path))
    status = get_status(db)

    html = _render_dashboard(kindle_status=status)

    assert "Latest Kindle import" in html
    assert "/import/kindle/scan-now" in html
    assert "Scan now" in html


def test_dashboard_omits_kindle_card_when_disabled(
    db, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("KINDLE_IMPORTS_DIR", raising=False)
    status = get_status(db)

    html = _render_dashboard(kindle_status=status)

    assert "Latest Kindle import" not in html
