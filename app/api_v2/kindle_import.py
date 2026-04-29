"""POST /api/v2/imports/kindle — browser-extension entry point.

Thin wrapper around :func:`app.importers.kindle_notebook.import_kindle_notebook_json`.
Authenticated by the existing ``Authorization: Token <value>`` scheme.
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlmodel import Session

from app.api_v2.auth import get_api_token
from app.db import get_session
from app.importers.kindle_notebook import import_kindle_notebook_json
from app.models import ApiToken

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/imports", tags=["v2-imports"])


@router.post("/kindle")
async def post_kindle_import(
    request: Request,
    token: ApiToken = Depends(get_api_token),
    session: Session = Depends(get_session),
) -> dict[str, Any]:
    raw = await request.body()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}")

    file_obj = io.BytesIO(json.dumps(payload).encode("utf-8"))
    try:
        result = import_kindle_notebook_json(file_obj, session, user_id=token.user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # pragma: no cover — defensive
        logger.exception("kindle import failed")
        raise HTTPException(status_code=500, detail=f"Import failed: {exc}")

    body = {
        "books_created": result.books_created,
        "books_matched": result.books_matched,
        "highlights_created": result.highlights_created,
        "highlights_skipped_duplicates": result.highlights_skipped_duplicates,
        "errors": list(result.errors),
    }
    if result.errors:
        return {**body, "_status": "partial"}
    return body
