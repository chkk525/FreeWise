from dataclasses import asdict
from typing import Any, Dict
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select, func
from datetime import datetime, date

from app.db import get_session, get_settings, get_current_streak
from app.models import Book, Highlight, Settings, ReviewSession
from app.services.kindle_import_status import get_status as get_kindle_status


router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = Jinja2Templates(directory="app/templates")



@router.get("/ui", response_class=HTMLResponse)
async def ui_dashboard(
    request: Request,
    session: Session = Depends(get_session),
):
    """
    Render dashboard page with statistics overview and review CTA.
    """
    # Get settings for theme and daily review count
    settings = get_settings(session)

    daily_review_count = settings.daily_review_count if settings else 5
    
    # Check if user has completed review today via DB
    today_date = date.today()
    completed_today_stmt = (
        select(ReviewSession)
        .where(ReviewSession.session_date == today_date)
        .where(ReviewSession.is_completed == True)
    )
    completed_today = session.exec(completed_today_stmt).first()
    reviewed_today = completed_today is not None
    highlights_reviewed_count = completed_today.highlights_reviewed if completed_today else 0
    
    # Get total books count
    books_count_stmt = select(func.count(Book.id))
    total_books = session.exec(books_count_stmt).one()
    
    # Get total highlights count
    highlights_count_stmt = select(func.count(Highlight.id))
    total_highlights = session.exec(highlights_count_stmt).one()
    
    # Get total favorited highlights
    favorited_stmt = select(func.count(Highlight.id)).where(
        Highlight.is_favorited == True
    )
    total_favorited = session.exec(favorited_stmt).one()
    
    # Get total discarded highlights
    discarded_stmt = select(func.count(Highlight.id)).where(
        Highlight.is_discarded == True
    )
    total_discarded = session.exec(discarded_stmt).one()
    
    # Calculate active highlights (not discarded)
    active_highlights = total_highlights - total_discarded
    
    # Calculate percentages for visualization
    favorited_percentage = (total_favorited / total_highlights * 100) if total_highlights > 0 else 0
    discarded_percentage = (total_discarded / total_highlights * 100) if total_highlights > 0 else 0
    active_percentage = (active_highlights / total_highlights * 100) if total_highlights > 0 else 0
    
    # Generate heatmap data via SQL GROUP BY — no full table scan
    heatmap_stmt = (
        select(func.date(Highlight.created_at), func.count(Highlight.id))
        .where(Highlight.created_at != None)
        .group_by(func.date(Highlight.created_at))
    )
    heatmap_data: Dict[str, int] = {
        str(row[0]): row[1] for row in session.exec(heatmap_stmt).all()
    }
    
    # Review activity heatmap: aggregate distinct review-days SQL-side instead
    # of hydrating every ReviewSession row into Python (perf H3). Binary 1/0
    # per day is preserved by collapsing the per-row count to "exists".
    review_dates_stmt = (
        select(ReviewSession.session_date)
        .where(ReviewSession.is_completed == True)  # noqa: E712
        .distinct()
        .order_by(ReviewSession.session_date.asc())
    )
    completed_dates = list(session.exec(review_dates_stmt).all())
    review_heatmap_data: Dict[str, int] = {d.isoformat(): 1 for d in completed_dates}

    # Current streak — shared utility (same logic used by the nav middleware)
    current_streak = get_current_streak(session)
    longest_streak = 0

    if completed_dates:
        # Longest-ever streak from the already-distinct sorted list.
        temp_streak = 1
        longest_streak = 1
        for i in range(1, len(completed_dates)):
            days_diff = (completed_dates[i] - completed_dates[i - 1]).days
            if days_diff == 1:
                temp_streak += 1
                longest_streak = max(longest_streak, temp_streak)
            else:
                temp_streak = 1

    kindle_status = get_kindle_status(session)

    # Tag cloud — counts of highlight-level tags, sorted desc, capped to keep
    # the dashboard widget readable. Single GROUP BY query — no N+1.
    from app.models import HighlightTag, Tag
    tag_counts_stmt = (
        select(Tag.name, func.count(HighlightTag.tag_id))
        .join(HighlightTag, HighlightTag.tag_id == Tag.id)
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(Tag.name)
        .order_by(func.count(HighlightTag.tag_id).desc())
        .limit(40)
    )
    tag_cloud: list[dict[str, object]] = []
    for name, count in session.exec(tag_counts_stmt).all():
        if name and name.lower() not in ("favorite", "discard"):
            tag_cloud.append({"name": name, "count": count})
    # Pre-compute a font-size bucket (1..5) per tag so the template stays clean.
    if tag_cloud:
        max_count = max(t["count"] for t in tag_cloud)
        for t in tag_cloud:
            ratio = t["count"] / max_count if max_count else 0
            # 1..5 buckets for sm/base/lg/xl/2xl in the template.
            t["size"] = max(1, min(5, 1 + int(ratio * 4 + 0.5)))

    return templates.TemplateResponse(request, "dashboard.html", {"settings": settings,
        "daily_review_count": daily_review_count,
        "reviewed_today": reviewed_today,
        "highlights_reviewed_count": highlights_reviewed_count,
        "total_books": total_books,
        "total_highlights": total_highlights,
        "active_highlights": active_highlights,
        "total_favorited": total_favorited,
        "total_discarded": total_discarded,
        "favorited_percentage": favorited_percentage,
        "discarded_percentage": discarded_percentage,
        "active_percentage": active_percentage,
        "heatmap_data": heatmap_data,
        "review_heatmap_data": review_heatmap_data,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "tag_cloud": tag_cloud,
        "kindle_status": kindle_status})


@router.get("/kindle/status")
def kindle_status(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Return JSON snapshot of Kindle import state for dashboards / probes."""
    return asdict(get_kindle_status(session))
