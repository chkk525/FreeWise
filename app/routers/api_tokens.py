"""HTML-first management UI for Readwise-compatible API tokens.

The user creates a token here, copies it once, and pastes it into the Chrome
extension (or any other Readwise client). On v1 the raw token is stored in
the database — see the comment in :func:`create_api_token` for the rationale
and a pointer to the planned hashed-token migration.
"""

from __future__ import annotations

import logging
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session, get_settings
from app.models import ApiToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import/api-token", tags=["api-tokens"])
templates = Jinja2Templates(directory="app/templates")


def _list_tokens(session: Session) -> list[ApiToken]:
    return list(
        session.exec(select(ApiToken).order_by(ApiToken.created_at.desc())).all()
    )


@router.get("", response_class=HTMLResponse)
async def view_api_tokens(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render the API-token management page."""
    settings = get_settings(session)
    tokens = _list_tokens(session)
    return templates.TemplateResponse(
        "api_tokens.html",
        {
            "request": request,
            "settings": settings,
            "tokens": tokens,
            "new_token": None,
        },
    )


@router.post("", response_class=HTMLResponse)
async def create_api_token(
    request: Request,
    name: str = Form(...),
    user_id: int = Form(default=1),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Create a new API token and render the page with the secret shown once.

    NOTE: For v1 we persist the raw token (the ``ApiToken.token`` column).
    This keeps the implementation simple while the API surface is small and
    the deployment is single-user. A future migration should replace the
    column with a hashed value plus a short prefix for lookup. See
    ``docs/superpowers/plans/2026-04-19-readwise-api-and-chrome-extension.md``
    for the planned change.
    """
    settings = get_settings(session)
    label = name.strip() or "unnamed"
    raw_token = secrets.token_hex(32)  # 64 hex characters

    token = ApiToken(token=raw_token, name=label, user_id=user_id)
    session.add(token)
    session.commit()
    session.refresh(token)
    logger.info("api_v2: created token id=%s name=%s", token.id, token.name)

    tokens = _list_tokens(session)
    return templates.TemplateResponse(
        "api_tokens.html",
        {
            "request": request,
            "settings": settings,
            "tokens": tokens,
            "new_token": raw_token,
            "new_token_name": label,
        },
    )
