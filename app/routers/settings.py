from typing import Optional
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func

from app.db import get_session, get_settings
from app.models import Settings, Highlight


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
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "highlights_count": highlights_count
    })


@router.post("/ui", response_class=HTMLResponse)
async def update_settings_ui(
    request: Request,
    daily_review_count: int = Form(...),
    theme: str = Form(...),
    session: Session = Depends(get_session)
):
    """Update settings from form submission."""
    settings = get_settings(session)
    
    settings.daily_review_count = max(1, min(15, daily_review_count))
    settings.theme = theme
    
    session.add(settings)
    session.commit()
    session.refresh(settings)
    
    highlights_count_stmt = select(func.count(Highlight.id))
    highlights_count = session.exec(highlights_count_stmt).one()
    
    # Return updated form with success message
    return templates.TemplateResponse("settings.html", {
        "request": request,
        "settings": settings,
        "highlights_count": highlights_count,
        "success_message": "Settings saved successfully!"
    })
