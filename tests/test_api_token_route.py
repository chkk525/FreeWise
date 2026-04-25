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

    def TemplateResponse(self, name, context, **kwargs):  # noqa: N802 (Starlette API)
        self.calls.append((name, context))
        # Return any object with a status_code so calling code is happy.
        from starlette.responses import Response
        return Response(content=context.get("new_token") or "", status_code=200)


def test_get_api_token_handler_returns_token_list(db: Session):
    db.add(ApiToken(token="existing-tok", name="laptop", user_id=1))
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
                user_id=1,
                session=db,
            )
        )

    rows = db.exec(select(ApiToken).where(ApiToken.name == "my-extension")).all()
    assert len(rows) == 1
    raw = rows[0].token
    assert len(raw) == 64  # 32 bytes hex
    # Handler exposes the raw token in template context exactly once.
    _, context = dummy.calls[0]
    assert context["new_token"] == raw
    assert context["new_token_name"] == "my-extension"


def test_post_with_blank_name_uses_fallback(db: Session):
    dummy = _DummyTemplate()
    request = _build_request()
    with patch.object(api_tokens_module, "templates", dummy):
        _run(
            api_tokens_module.create_api_token(
                request, name="   ", user_id=1, session=db
            )
        )

    rows = db.exec(select(ApiToken).where(ApiToken.name == "unnamed")).all()
    assert len(rows) == 1


def test_route_is_mounted_on_app():
    """The router must be registered on the FastAPI app under the documented path."""
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/import/api-token" in paths
