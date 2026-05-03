"""Tests for the /import/api-token management UI.

NOTE: a Starlette/Jinja2/Python 3.14 LRUCache incompatibility (the documented
"92 starlette pre-existing baseline" of HTML-rendering tests) crashes the
``Jinja2Templates.get_template`` call before any of our route code runs. Until
the parallel starlette fix is merged we exercise the route's *behaviour* by
calling the handler directly with a stub ``Request`` and asserting on the DB
side-effects + the rendered context. This sidesteps the template cache entirely
so our tests don't pile onto the baseline.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sqlmodel import Session, select
from starlette.requests import Request

from app.models import ApiToken
from app.routers import api_tokens as api_tokens_module


def _build_request() -> Request:
    """Minimal ASGI scope so the handler's ``Request`` argument is satisfied."""
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/import/api-token",
        "headers": [],
        "query_string": b"",
    }
    return Request(scope)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class _DummyTemplate:
    """Capture context passed to ``templates.TemplateResponse`` without rendering."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def TemplateResponse(self, *args, **kwargs):  # noqa: N802 (Starlette API)
        # Modern signature: TemplateResponse(request, name, context, ...)
        # Legacy signature: TemplateResponse(name, context, ...)
        # Accept both so this stub works pre/post-migration.
        if len(args) >= 3:
            _request, name, context = args[0], args[1], args[2]
        elif len(args) == 2:
            name, context = args[0], args[1]
        else:
            name, context = kwargs.get("name", ""), kwargs.get("context", {})
        self.calls.append((name, context))
        from starlette.responses import Response
        return Response(content=context.get("new_token") or "", status_code=200)


def test_get_api_token_handler_returns_token_list(db: Session):
    db.add(ApiToken(token_hash="abc", token_prefix="laptop-prefix01", name="laptop", user_id=1))
    db.commit()

    dummy = _DummyTemplate()
    request = _build_request()
    with patch.object(api_tokens_module, "templates", dummy):
        resp = _run(api_tokens_module.view_api_tokens(request, session=db))

    assert resp.status_code == 200
    assert dummy.calls, "handler must render the api_tokens template"
    template_name, context = dummy.calls[0]
    assert template_name == "api_tokens.html"
    assert context["new_token"] is None
    names = [t.name for t in context["tokens"]]
    assert "laptop" in names


def test_post_creates_token_and_shows_it_once(db: Session):
    dummy = _DummyTemplate()
    request = _build_request()
    with patch.object(api_tokens_module, "templates", dummy):
        _run(
            api_tokens_module.create_api_token(
                request,
                name="my-extension",
                session=db,
            )
        )

    rows = db.exec(select(ApiToken).where(ApiToken.name == "my-extension")).all()
    assert len(rows) == 1
    row = rows[0]
    # Plaintext column must NOT be persisted for new rows.
    assert row.token is None
    # Hash + prefix must be set.
    assert row.token_hash and len(row.token_hash) == 64
    assert row.token_prefix and len(row.token_prefix) == 16
    assert row.user_id == 1  # hard-coded, not user-controlled
    # Handler exposes the raw token in template context exactly once.
    _, context = dummy.calls[0]
    raw = context["new_token"]
    assert raw.startswith("fw_")
    assert len(raw) == 67  # "fw_" + 64 hex chars
    # The hash + prefix MUST match the raw token shown.
    import hashlib
    assert row.token_prefix == raw[:16]
    assert row.token_hash == hashlib.sha256(raw.encode("utf-8")).hexdigest()
    assert context["new_token_name"] == "my-extension"


def test_post_with_blank_name_uses_fallback(db: Session):
    dummy = _DummyTemplate()
    request = _build_request()
    with patch.object(api_tokens_module, "templates", dummy):
        _run(
            api_tokens_module.create_api_token(
                request, name="   ", session=db
            )
        )

    rows = db.exec(select(ApiToken).where(ApiToken.name == "unnamed")).all()
    assert len(rows) == 1


def test_route_is_mounted_on_app():
    """The router must be registered on the FastAPI app under the documented path."""
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/import/api-token" in paths


# ── CSRF + revocation (Phase 4 hardening) ───────────────────────────────────


def _build_request_with_origin(origin: str | None) -> Request:
    """Same as _build_request() but with an Origin header.

    Pass origin=None to omit the header entirely (browser stripped it).
    """
    headers = []
    if origin is not None:
        headers.append((b"origin", origin.encode("utf-8")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/import/api-token",
        "headers": headers,
        "query_string": b"",
        "server": ("testserver", 80),
        "scheme": "http",
    }
    return Request(scope)


def test_post_rejects_cross_origin(db: Session):
    """A POST whose Origin doesn't match the request host must 403."""
    from fastapi import HTTPException
    request = _build_request_with_origin("https://evil.example.com")
    dummy = _DummyTemplate()
    with patch.object(api_tokens_module, "templates", dummy):
        try:
            _run(api_tokens_module.create_api_token(request, name="x", session=db))
        except HTTPException as exc:
            assert exc.status_code == 403
        else:
            raise AssertionError("expected HTTPException(403)")
    # Nothing committed
    assert db.exec(select(ApiToken)).first() is None


def test_post_allows_missing_origin(db: Session):
    """Same-site form posts strip Origin in some browsers — that path is OK."""
    request = _build_request_with_origin(None)
    dummy = _DummyTemplate()
    with patch.object(api_tokens_module, "templates", dummy):
        _run(api_tokens_module.create_api_token(request, name="ok", session=db))
    rows = db.exec(select(ApiToken).where(ApiToken.name == "ok")).all()
    assert len(rows) == 1


def test_revoke_deletes_token(db: Session):
    db.add(ApiToken(token_hash="abc", token_prefix="prefix1234567890", name="doomed", user_id=1))
    db.commit()
    row = db.exec(select(ApiToken).where(ApiToken.name == "doomed")).one()
    request = _build_request_with_origin(None)  # same-host, no Origin → allowed
    _run(api_tokens_module.revoke_api_token(row.id, request, session=db))
    assert db.exec(select(ApiToken).where(ApiToken.name == "doomed")).first() is None


def test_user_id_is_not_form_controlled(db: Session):
    """Even if a request body included user_id=999, the route must ignore it."""
    request = _build_request_with_origin(None)
    dummy = _DummyTemplate()
    with patch.object(api_tokens_module, "templates", dummy):
        # user_id is NOT a parameter to create_api_token — we test that the
        # signature itself doesn't accept it.
        import inspect
        sig = inspect.signature(api_tokens_module.create_api_token)
        assert "user_id" not in sig.parameters
