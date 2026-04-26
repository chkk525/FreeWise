from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from app.db import get_session, get_settings
from app.models import Settings, Highlight

THEME_CYCLE = ("light", "dark", "auto")


router = APIRouter(prefix="/settings", tags=["settings"])
templates = Jinja2Templates(directory="app/templates")


# ============ HTML/HTMX Endpoints ============

@router.get("/ui", response_class=HTMLResponse)
async def ui_settings(
    request: Request,
    session: Session = Depends(get_session)
):
    """Render settings page with form."""
    settings = get_settings(session)
    highlights_count_stmt = select(func.count(Highlight.id))
    highlights_count = session.exec(highlights_count_stmt).one()
    return templates.TemplateResponse(request, "settings.html", {"settings": settings,
        "highlights_count": highlights_count})


@router.post("/ui", response_class=HTMLResponse)
async def update_settings_ui(
    request: Request,
    daily_review_count: int = Form(...),
    highlight_recency: int = Form(...),
    theme: str = Form(...),
    session: Session = Depends(get_session)
):
    """Update settings from form submission."""
    settings = get_settings(session)
    
    settings.daily_review_count = max(1, min(15, daily_review_count))
    settings.highlight_recency = max(0, min(10, highlight_recency))
    settings.theme = theme
    
    session.add(settings)
    session.commit()
    session.refresh(settings)
    
    highlights_count_stmt = select(func.count(Highlight.id))
    highlights_count = session.exec(highlights_count_stmt).one()
    
    # Return updated form with success message
    return templates.TemplateResponse(request, "settings.html", {"settings": settings,
        "highlights_count": highlights_count,
        "success_message": "Settings saved successfully!"})


@router.post("/theme/toggle")
async def toggle_theme(session: Session = Depends(get_session)):
    """Advance the theme through light → dark → auto → light.

    Returns 204 with HX-Refresh so the htmx-driven nav button reloads the
    page and `data-theme` re-renders against the new value. Non-htmx
    callers see the same status and can read the new value from the
    `X-Theme` response header.
    """
    settings = get_settings(session)
    current = settings.theme if settings.theme in THEME_CYCLE else "light"
    next_theme = THEME_CYCLE[(THEME_CYCLE.index(current) + 1) % len(THEME_CYCLE)]
    settings.theme = next_theme
    session.add(settings)
    session.commit()
    return Response(
        status_code=204,
        headers={"HX-Refresh": "true", "X-Theme": next_theme},
    )


@router.post("/reset-library", response_class=HTMLResponse)
async def reset_library(request: Request):
    """Permanently drop and recreate every table, then reinitialise default settings."""
    from sqlmodel import SQLModel, Session
    from app.db import get_engine

    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        fresh_settings = get_settings(s)
        return templates.TemplateResponse(request, "settings.html", {"settings": fresh_settings,
            "highlights_count": 0,
            "success_message": "Library reset — all data has been permanently deleted and settings restored to defaults."})
