"""Unit tests for app.services.notifier."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.services import notifier


def test_disabled_when_url_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(notifier.NOTIFY_URL_ENV, raising=False)
    assert notifier.notify("failure", "msg") is False


def test_skipped_when_mode_never(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(notifier.NOTIFY_URL_ENV, "https://example.invalid/hook")
    monkeypatch.setenv(notifier.NOTIFY_ON_ENV, "never")
    assert notifier.notify("failure", "msg") is False


def test_skipped_when_mode_failure_and_status_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(notifier.NOTIFY_URL_ENV, "https://example.invalid/hook")
    monkeypatch.setenv(notifier.NOTIFY_ON_ENV, "failure")
    assert notifier.notify("success", "msg") is False


def test_posts_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    received: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received["url"] = str(request.url)
        received["body"] = json.loads(request.content.decode())
        return httpx.Response(200, text="ok")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv(notifier.NOTIFY_URL_ENV, "https://example.invalid/hook")
    monkeypatch.setenv(notifier.NOTIFY_ON_ENV, "always")
    monkeypatch.setenv(notifier.NOTIFY_HOST_ENV, "test-host")

    # Patch httpx.Client to use our mock transport
    real_client = httpx.Client

    def patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)

    ok = notifier.notify(
        "success", "imported 49 books", extra={"files_imported": 1}
    )
    assert ok is True
    body = received["body"]
    assert body["status"] == "success"
    assert body["host"] == "test-host"
    assert body["service"] == "freewise"
    assert body["files_imported"] == 1
    assert "imported 49 books" in body["text"]


def test_5xx_returns_false_no_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="oops")

    transport = httpx.MockTransport(handler)
    monkeypatch.setenv(notifier.NOTIFY_URL_ENV, "https://example.invalid/hook")
    monkeypatch.setenv(notifier.NOTIFY_ON_ENV, "always")

    real_client = httpx.Client

    def patched_client(*args: Any, **kwargs: Any) -> httpx.Client:
        kwargs["transport"] = transport
        return real_client(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", patched_client)

    assert notifier.notify("failure", "boom") is False


def test_redact_strips_path() -> None:
    redacted = notifier._redact(
        "https://hooks.slack.com/services/T123/B456/secret-token"
    )
    assert redacted == "https://hooks.slack.com/…"
