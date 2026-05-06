"""Shared security helpers for HTML and API routes."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


def check_same_origin(request: Request) -> None:
    """Reject unsafe requests whose Origin or Referer is not same-host.

    Browsers may omit Origin on same-origin form posts, so absence is allowed.
    A present Origin/Referer must match the request host exactly.
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    candidate = origin or referer
    if not candidate:
        return

    candidate_host = urlparse(candidate).netloc
    if not candidate_host:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request rejected: malformed Origin/Referer",
        )

    request_host = request.url.netloc
    if candidate_host != request_host:
        logger.warning(
            "csrf: origin=%s referer=%s does not match host=%s",
            origin,
            referer,
            request_host,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-origin request rejected",
        )
