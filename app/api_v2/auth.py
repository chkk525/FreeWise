"""Bearer-token authentication for the Readwise-compatible ``/api/v2`` routes.

Readwise uses a non-standard ``Authorization: Token <value>`` header (the
literal word ``Token``, not ``Bearer``). Existing Readwise clients send the
header verbatim, so we match the scheme exactly. Anything else — including
the standard ``Bearer`` scheme — is rejected with ``401``.

Token storage model (Phase 4 hardening):
  * ``ApiToken.token_hash`` is the canonical column — sha256 of the raw token.
  * ``ApiToken.token_prefix`` is the indexed first 16 hex chars used to find
    candidate rows quickly without a table scan.
  * ``ApiToken.token`` (legacy plaintext) is read as a fallback for rows that
    pre-date the migration; on hit, the row is opportunistically upgraded
    to hash storage and the plaintext column is cleared.
  * Comparison uses :func:`hmac.compare_digest` to avoid timing leaks.

Usage::

    from fastapi import Depends
    from app.api_v2.auth import get_api_token

    @router.get("/something")
    def something(token: ApiToken = Depends(get_api_token)):
        ...
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from datetime import datetime, UTC
from threading import Lock
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from sqlmodel import Session, select

from app.db import get_session
from app.models import ApiToken

logger = logging.getLogger(__name__)

# The exact scheme word Readwise uses. Constant so tests + callers don't drift.
TOKEN_SCHEME = "Token"

# Hot-path optimisation: don't write last_used_at on every API request.
# Records when each token id was last touched in process memory; only commits
# the column when ≥ this many seconds have elapsed since the last write.
# Drops API throughput pressure on SQLite's single writer dramatically when a
# Chrome extension polls the same token in a tight loop.
_LAST_USED_DEBOUNCE_SECONDS = 300
_last_used_at_cache: dict[int, float] = {}
_last_used_at_lock = Lock()


def _hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _prefix_of(raw: str) -> str:
    """Return the indexed lookup prefix (first 16 hex chars). Safe to log."""
    return raw[:16]


def _maybe_touch_last_used_at(session: Session, row: ApiToken) -> None:
    """Refresh ``last_used_at`` at most once per token per debounce window."""
    if row.id is None:
        return
    now_monotonic = time.monotonic()
    with _last_used_at_lock:
        previous = _last_used_at_cache.get(row.id, 0.0)
        if now_monotonic - previous < _LAST_USED_DEBOUNCE_SECONDS:
            return
        _last_used_at_cache[row.id] = now_monotonic
    row.last_used_at = datetime.now(UTC).replace(tzinfo=None)
    session.add(row)
    session.commit()


def _candidate_rows(session: Session, raw_token: str) -> list[ApiToken]:
    """Return rows whose hash OR plaintext could match the supplied token.

    Lookup order:
      1. token_hash == sha256(raw)  ← cheap indexed equality
      2. token == raw               ← legacy plaintext fallback (one-time)
    """
    h = _hash_token(raw_token)
    rows = list(
        session.exec(
            select(ApiToken).where(ApiToken.token_hash == h)
        ).all()
    )
    if rows:
        return rows
    # Legacy fallback. Limit to a single row's worth of memory by querying on
    # the equality predicate directly.
    legacy = list(
        session.exec(
            select(ApiToken).where(ApiToken.token == raw_token)
        ).all()
    )
    return legacy


def _upgrade_legacy_row(session: Session, row: ApiToken, raw_token: str) -> None:
    """Hash a legacy plaintext row in place. Idempotent."""
    if row.token_hash:
        return
    row.token_hash = _hash_token(raw_token)
    row.token_prefix = _prefix_of(raw_token)
    # Clear the plaintext column so a subsequent DB leak cannot reuse it.
    row.token = None
    session.add(row)
    session.commit()
    logger.info("api_v2 auth: upgraded legacy token row id=%s to hashed storage", row.id)


def get_api_token(
    authorization: Optional[str] = Header(default=None),
    session: Session = Depends(get_session),
) -> ApiToken:
    """Resolve and return the :class:`ApiToken` row matching the request header.

    Raises ``HTTPException(401)`` on any failure (missing header, wrong scheme,
    malformed value, unknown token). On success the token's ``last_used_at``
    is refreshed at most once per ``_LAST_USED_DEBOUNCE_SECONDS`` window so a
    polling client doesn't serialise on the SQLite writer.
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

    candidates = _candidate_rows(session, token_value)
    matched: Optional[ApiToken] = None
    expected_hash = _hash_token(token_value)
    for row in candidates:
        # Constant-time comparison even though the index already short-listed
        # — this guards against future code paths that might widen the lookup.
        if row.token_hash and hmac.compare_digest(row.token_hash, expected_hash):
            matched = row
            break
        if row.token and hmac.compare_digest(row.token, token_value):
            matched = row
            _upgrade_legacy_row(session, row, token_value)
            break

    if matched is None:
        # Don't echo the supplied token back in logs/responses — treat it as
        # a secret even when it's wrong.
        logger.info("api_v2 auth: unknown token rejected")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    _maybe_touch_last_used_at(session, matched)
    return matched
