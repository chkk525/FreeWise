"""Dashboard route for uploading the Kindle scraper's storage_state.json."""
from __future__ import annotations

import os
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services.kindle_cookie import (
    CookieValidationError,
    ScrapeRunningError,
    read_storage_state_status,
    write_storage_state,
)

router = APIRouter(prefix="/dashboard/kindle", tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")


def _target_path() -> Path:
    base = os.environ.get(
        "KINDLE_STATE_PATH",
        "/share/Container/freewise/state/kindle",
    )
    return Path(base) / "storage_state.json"


@router.get("/cookie", response_class=HTMLResponse)
async def get_cookie_page(request: Request) -> HTMLResponse:
    status = read_storage_state_status(_target_path())
    return templates.TemplateResponse(
        request, "kindle_cookie.html", {"status": status}
    )


@router.post("/cookie", response_class=HTMLResponse)
async def post_cookie(
    request: Request,
    file: UploadFile = File(...),
) -> HTMLResponse:
    payload = await file.read()
    try:
        status = write_storage_state(payload, target_path=_target_path())
    except CookieValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except ScrapeRunningError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return templates.TemplateResponse(
        request, "_kindle_cookie_status.html",
        {"status": status, "success": True},
    )
