"""Bearer-token authentication for the Readwise-compatible ``/api/v2`` routes.

Readwise uses a non-standard ``Authorization: Token <value>`` header (the
literal word ``Token``, not ``Bearer``). Existing Readwise clients send the
header verbatim, so we match the scheme exactly. Anything else — including
the standard ``Bearer`` scheme — is rejected with ``401``.

Usage::

    from fastapi import Depends
    from app.api_v2.auth import get_api_token

    @router.get("/something")
    def something(token: ApiToken = Depends(get_api_token)):
        ...
"""

from __future__ import annotations

import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.db import get_session
from app.models import ApiToken

logger = logging.getLogger(__name__)

# The exact scheme word Readwise uses. Constant so tests + callers don't drift.
TOKEN_SCHEME = "Token"


def get_api_token(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> ApiToken:
    """Resolve and return the :class:`ApiToken` row matching the request header.

    Raises ``HTTPException(401)`` on any failure (missing header, wrong scheme,
    malformed value, unknown token). On success the token's ``last_used_at`` is
    refreshed so the user can audit which tokens are still active.
    """
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": f'{TOKEN_SCHEME} realm="freewise"'},
        )

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0] != TOKEN_SCHEME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid Authorization scheme; expected '{TOKEN_SCHEME} <value>'",
        )

    token_value = parts[1].strip()
    if not token_value:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Empty token value",
        )

    row = session.exec(
        select(ApiToken).where(ApiToken.token == token_value)
    ).first()
    if row is None:
        # Don't echo the supplied token back in logs/responses — treat it as a
        # secret even when it's wrong.
        logger.info("api_v2 auth: unknown token rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
