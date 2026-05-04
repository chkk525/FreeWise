"""GET /digest/today — a deterministic-per-day digest page.

Same content all day for a given calendar date so the URL is shareable
and CDN-cacheable. Builds on ``app.services.digest.today_picks`` for
the deterministic sampler and reuses ``_today_pick`` / ``_on_this_day``
/ ``_library_health`` for the single-pick + on-this-day +
library-health surfaces shown alongside.

The page lives behind the same Cloudflare Access gate as the rest of
the HTML UI; no per-user auth happens at the FastAPI layer.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from app.db import get_session, get_settings
from app.services.digest import (
    _library_health,
    _on_this_day,
    _today_pick,
    today_picks,
)
from app.template_filters import make_templates


router = APIRouter(prefix="/digest", tags=["digest"])
templates = make_templates()


# Roughly the time it takes for clock-skewed clients to roll over;
# also small enough that an 11pm visit doesn't wedge tomorrow's digest
# behind a stale cache. The daily set itself is fully deterministic, so
# the upper bound is just "long enough to skip a re-render on the same
# page-reload but short enough to roll forward at midnight".
_DIGEST_CACHE_SECONDS = 1800  # 30 min


@router.get("/today", response_class=HTMLResponse)
async def ui_digest_today(
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Render today's deterministic digest page."""
    settings = get_settings(session)
    today = date.today()
    picks = today_picks(session, count=10, user_id=1, today=today)
    today_one = _today_pick(session, user_id=1)
    on_this_day = _on_this_day(session, user_id=1, limit=5)
    health = _library_health(session, user_id=1)
    response = templates.TemplateResponse(
        request,
        "digest_today.html",
        {
            "settings": settings,
            "today": today,
            "picks": picks,
            "today_pick": today_one,
            "on_this_day": on_this_day,
            "health": health,
        },
    )
    # Cacheable by the browser / any intermediate proxy. The content is
    # 100% deterministic from the server's calendar date, so a fresh
    # render on the next day is fine; we just don't want to re-pay the
    # SQL cost on every refresh inside the same day.
    response.headers["Cache-Control"] = (
        f"private, max-age={_DIGEST_CACHE_SECONDS}"
    )
    return response
