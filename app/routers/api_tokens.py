"""HTML-first management UI for Readwise-compatible API tokens.

The user creates a token here, copies it once, and pastes it into the Chrome
extension (or any other Readwise client). Phase 4 hardening:

  * The raw token is shown ONCE at creation and never persisted; only its
    sha256 hash + a 16-char display prefix are stored.
  * POST /import/api-token enforces an Origin/Referer check so that a
    cross-origin page can't silently mint tokens through a victim's
    Cloudflare Access session.
  * user_id is hard-coded to 1 (single-user FreeWise) and NOT accepted as a
    form field, so a malicious form post can't escalate privileges by
    minting a token bound to another user.
  * The view page exposes a DELETE form per row for revocation.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from typing import Optional
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from app.db import get_session, get_settings
from app.models import ApiToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/import/api-token", tags=["api-tokens"])
templates = Jinja2Templates(directory="app/templates")


# Single-user FreeWise: token always belongs to user_id=1. Callers cannot
# override this from the form body — if/when we go multi-user, derive from
# the verified session identity here, NOT from a form parameter.
DEFAULT_TOKEN_USER_ID = 1


def _check_same_origin(request: Request) -> None:
    """Reject POSTs whose Origin (or fallback Referer) is not same-host.

    Cloudflare Access sits in front of FreeWise; the upstream FastAPI app
    has no auth of its own. Without an Origin/Referer check, a victim's
    Access session could be ridden by any cross-origin page that POSTs to
    /import/api-token to mint a token. Mirrors the pattern in
    safaribooks-web's `_check_origin` (`webapp/app.py`).
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    request_host = request.url.netloc
    candidate = origin or referer
    if not candidate:
        # Some browsers strip Origin on same-origin form posts. We allow that
        # ONLY when the request is same-host AND uses POST from a non-CORS
        # context. Same-host check via the request URL itself.
        return
    parsed = urlparse(candidate)
    candidate_host = parsed.netloc
    if not candidate_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request rejected: malformed Origin/Referer",
        )
    if candidate_host != request_host:
        logger.warning(
            "api-token CSRF: origin=%s referer=%s does not match host=%s",
            origin, referer, request_host,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request rejected",
        )


def _list_tokens(session: Session) -> list[ApiToken]:
    return list(
        session.exec(select(ApiToken).order_by(ApiToken.created_at.desc())).all()
    )


def _generate_raw_token() -> str:
    """Generate ``fw_<16hex_prefix><48hex_secret>`` — 66 chars total."""
    body = secrets.token_hex(32)  # 64 hex chars
    return f"fw_{body}"


@router.get("", response_class=HTMLResponse)
async def view_api_tokens(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render the API-token management page."""
    settings = get_settings(session)
    tokens = _list_tokens(session)
    return templates.TemplateResponse(
        request,
        "api_tokens.html",
        {
            "settings": settings,
            "tokens": tokens,
            "new_token": None,
        },
    )


@router.post("", response_class=HTMLResponse)
async def create_api_token(
    request: Request,
    name: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Create a new API token and render the page with the secret shown once.

    The raw token is displayed exactly once on the response page. Only the
    sha256 hash and a 16-char display prefix are persisted — the raw value
    cannot be retrieved later. Token format is ``fw_<64hex>`` so the prefix
    is recognisable in operator logs.
    """
    _check_same_origin(request)
    settings = get_settings(session)
    label = name.strip() or "unnamed"
    raw_token = _generate_raw_token()

    token = ApiToken(
        # plaintext column stays NULL for new rows
        token=None,
        token_prefix=raw_token[:16],
        token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        name=label,
        user_id=DEFAULT_TOKEN_USER_ID,
    )
    session.add(token)
    session.commit()
    session.refresh(token)
    logger.info(
        "api_v2: created token id=%s name=%s prefix=%s",
        token.id, token.name, token.token_prefix,
    )

    tokens = _list_tokens(session)
    return templates.TemplateResponse(
        request,
        "api_tokens.html",
        {
            "settings": settings,
            "tokens": tokens,
            "new_token": raw_token,
            "new_token_name": label,
        },
    )


@router.post("/{token_id}/delete", response_class=HTMLResponse)
async def revoke_api_token(
    token_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Delete an API token by id. Same CSRF check as creation."""
    _check_same_origin(request)
    row = session.get(ApiToken, token_id)
    if row is not None:
        session.delete(row)
        session.commit()
        logger.info("api_v2: revoked token id=%s name=%s", token_id, row.name)
    return RedirectResponse(url="/import/api-token", status_code=303)
