from dataclasses import asdict
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import case
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select, func
from datetime import datetime, date, UTC

from app.db import get_current_streak, get_session, get_settings
from app.models import Book, Highlight, Settings, ReviewSession
from app.services.cold_books import cold_books as compute_cold_books
from app.services.echoes import get_echoes
from app.services.kindle_import_status import get_status as get_kindle_status
from app.services.review_log import counts_by_day as review_log_counts_by_day
from app.template_filters import make_templates


router = APIRouter(prefix="/dashboard", tags=["dashboard"])
templates = make_templates()


def _longest_streak(completed_dates: list[date]) -> int:
    if not completed_dates:
        return 0

    longest = 1
    current = 1
    for i in range(1, len(completed_dates)):
        days_diff = (completed_dates[i] - completed_dates[i - 1]).days
        if days_diff == 1:
            current += 1
            longest = max(longest, current)
        else:
            current = 1
    return longest



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
    
    # Highlight totals in one pass over the table instead of three separate
    # COUNT queries. Keeps the dashboard cheap on 20k+ row libraries.
    total_highlights, total_favorited, total_discarded = session.exec(
        select(
            func.count(Highlight.id),
            func.coalesce(
                func.sum(case((Highlight.is_favorited == True, 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((Highlight.is_discarded == True, 1), else_=0)),
                0,
            ),
        )
    ).one()
    
    # Calculate active highlights (not discarded)
    active_highlights = total_highlights - total_discarded
    
    # Calculate percentages for visualization
    favorited_percentage = (total_favorited / total_highlights * 100) if total_highlights > 0 else 0
    discarded_percentage = (total_discarded / total_highlights * 100) if total_highlights > 0 else 0
    active_percentage = (active_highlights / total_highlights * 100) if total_highlights > 0 else 0
    
    kindle_status = get_kindle_status(session)

    # Embedding coverage (C2) — what fraction of active highlights have a
    # vector for the current model. Single COUNT(DISTINCT) query.
    from app.models import Embedding
    from app.services.embeddings import _env_model
    embed_model = _env_model()
    embedded_count = session.exec(
        select(func.count(func.distinct(Embedding.highlight_id)))
        .where(Embedding.model_name == embed_model)
    ).one() or 0
    embedding_coverage = {
        "model": embed_model,
        "embedded": int(embedded_count),
        "total_active": int(active_highlights),
        "percent": round(
            (int(embedded_count) / int(active_highlights) * 100) if active_highlights > 0 else 0.0,
            1,
        ),
    }

    # NOTE: library-health (duplicate hygiene + tagging coverage) and
    # on-this-day used to compute here, but at 25k+ highlights both
    # require full-table scans (strftime, GROUP BY substr, COUNT DISTINCT).
    # They're now defer-loaded via /dashboard/ui/health and
    # /dashboard/ui/on-this-day so the main page returns instantly.

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

    activity_counts = review_log_counts_by_day(session, days=7)
    activity_total = sum(c for _, c in activity_counts)
    activity_max = max((c for _, c in activity_counts), default=0)

    # Re-engagement surface: 5 books whose newest interaction is the
    # oldest in the library — i.e. long-tail imports the user has drifted
    # away from. Cheap query (one GROUP BY join) so it's safe inline.
    # Naive UTC for arithmetic against ``last_touched_at`` rows, which
    # are stored without tzinfo. ``datetime.now(UTC)`` keeps us off the
    # deprecated ``utcnow()`` API.
    _cold_now = datetime.now(UTC).replace(tzinfo=None)
    cold_books_view = [
        {
            "id": entry.id,
            "title": entry.title,
            "author": entry.author,
            "cover_image_url": entry.cover_image_url,
            "active_highlights": entry.active_highlights,
            "days_since": (
                (_cold_now - entry.last_touched_at).days
                if entry.last_touched_at is not None
                else None
            ),
        }
        for entry in compute_cold_books(session, limit=5)
    ]

    # Echoes — at most 3 cards drawn from anniversary / reread / neglect.
    # Cheap query: ≤6 small SELECTs with random() ordering. Returns []
    # gracefully when the library has no qualifying highlights.
    echoes = get_echoes(session, limit=3)

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
        "tag_cloud": tag_cloud,
        "embedding_coverage": embedding_coverage,
        "kindle_status": kindle_status,
        "activity_counts": activity_counts,
        "activity_total": activity_total,
        "activity_max": activity_max,
        "cold_books": cold_books_view,
        "echoes": echoes})


@router.get("/kindle/status")
def kindle_status(session: Session = Depends(get_session)) -> Dict[str, Any]:
    """Return JSON snapshot of Kindle import state for dashboards / probes."""
    return asdict(get_kindle_status(session))


@router.get("/ui/activity", response_class=HTMLResponse)
async def ui_dashboard_activity(
    request: Request,
    session: Session = Depends(get_session),
):
    """Defer-loaded activity partial: heatmaps + streak summary."""
    heatmap_stmt = (
        select(func.date(Highlight.created_at), func.count(Highlight.id))
        .where(Highlight.created_at != None)
        .group_by(func.date(Highlight.created_at))
    )
    heatmap_data: Dict[str, int] = {
        str(row[0]): row[1] for row in session.exec(heatmap_stmt).all()
    }

    review_dates_stmt = (
        select(ReviewSession.session_date)
        .where(ReviewSession.is_completed == True)  # noqa: E712
        .distinct()
        .order_by(ReviewSession.session_date.asc())
    )
    completed_dates = list(session.exec(review_dates_stmt).all())
    review_heatmap_data: Dict[str, int] = {d.isoformat(): 1 for d in completed_dates}

    return templates.TemplateResponse(
        request,
        "_dashboard_activity.html",
        {
            "settings": get_settings(session),
            "heatmap_data": heatmap_data,
            "review_heatmap_data": review_heatmap_data,
            "current_streak": get_current_streak(session),
            "longest_streak": _longest_streak(completed_dates),
        },
    )


@router.get("/kindle/scrape-status", response_class=HTMLResponse)
async def kindle_scrape_status_partial(request: Request) -> HTMLResponse:
    """HTMX partial — current scrape state + button. Polled by the
    dashboard card while a scrape is running.

    Renders one of three states:
      - disabled (KINDLE_SCRAPE_CMD unset) → small note, no button
      - idle    → "Scrape now" button
      - running → spinner + log tail + cancel button
    """
    from app.services.kindle_scrape_trigger import get_status as get_scrape_status
    status = get_scrape_status()
    return templates.TemplateResponse(
        request, "_kindle_scrape_status.html",
        {"scrape": status},
    )


@router.post("/kindle/scrape-now", response_class=HTMLResponse)
async def kindle_scrape_now(request: Request) -> HTMLResponse:
    """Kick off the Kindle scrape in the background. Returns the same
    partial as /kindle/scrape-status so HTMX can swap the card in place."""
    from app.services.kindle_scrape_trigger import (
        ScrapeAlreadyRunning,
        ScrapeNotConfigured,
        get_status as get_scrape_status,
        trigger_scrape,
    )
    try:
        status = trigger_scrape()
    except ScrapeNotConfigured:
        raise HTTPException(
            status_code=503,
            detail="Kindle scrape is not configured on this server (KINDLE_SCRAPE_CMD env var unset).",
        )
    except ScrapeAlreadyRunning:
        # Race: someone else just started one. Show the latest state so
        # the polling loop picks it up cleanly.
        status = get_scrape_status()
    return templates.TemplateResponse(
        request, "_kindle_scrape_status.html",
        {"scrape": status},
    )


@router.post("/kindle/scrape-cancel", response_class=HTMLResponse)
async def kindle_scrape_cancel(request: Request) -> HTMLResponse:
    """SIGTERM a running scrape. Idempotent — no-op if nothing's running."""
    from app.services.kindle_scrape_trigger import cancel_scrape
    status = await cancel_scrape()
    return templates.TemplateResponse(
        request, "_kindle_scrape_status.html",
        {"scrape": status},
    )


@router.get("/ui/health", response_class=HTMLResponse)
async def ui_dashboard_health(
    request: Request,
    session: Session = Depends(get_session),
):
    """Defer-loaded library-health partial: dup-group count + untagged count.

    Splits two full-table scans off the main dashboard handler so /dashboard/ui
    can return immediately. The partial is fetched via HTMX after page load.
    """
    from app.models import HighlightTag, Tag
    from app.services.embeddings import SEMANTIC_COVERAGE_THRESHOLD

    active_count = session.exec(
        select(func.count(Highlight.id))
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
    ).one() or 0
    active_count = int(active_count)

    dup_group_sizes = session.exec(
        select(func.count(Highlight.id))
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .group_by(func.substr(Highlight.text, 1, 80))
        .having(func.count(Highlight.id) >= 2)
    ).all()

    tagged_ids_count = session.exec(
        select(func.count(func.distinct(HighlightTag.highlight_id)))
        .join(Tag, Tag.id == HighlightTag.tag_id)
        .join(Highlight, Highlight.id == HighlightTag.highlight_id)
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(~Tag.name.in_(["favorite", "discard"]))
    ).one() or 0
    untagged_count = max(0, active_count - int(tagged_ids_count))

    # Embedding coverage % is recomputed here so the partial owns its
    # own state — the parent page no longer passes it through.
    from app.models import Embedding
    from app.services.embeddings import _env_model
    embed_model = _env_model()
    embedded_count = session.exec(
        select(func.count(func.distinct(Embedding.highlight_id)))
        .where(Embedding.model_name == embed_model)
    ).one() or 0
    coverage_pct = (
        (int(embedded_count) / active_count * 100) if active_count > 0 else 0.0
    )

    library_health = {
        "dup_groups": len(dup_group_sizes),
        "dup_redundant": sum(int(c) - 1 for c in dup_group_sizes),
        "semantic_ready": coverage_pct >= SEMANTIC_COVERAGE_THRESHOLD * 100,
        "untagged_count": untagged_count,
        "untagged_pct": round(
            (untagged_count / active_count * 100) if active_count > 0 else 0.0,
            1,
        ),
    }
    return templates.TemplateResponse(
        request, "_dashboard_health.html",
        {"library_health": library_health},
    )


@router.get("/ui/on-this-day", response_class=HTMLResponse)
async def ui_dashboard_on_this_day(
    request: Request,
    session: Session = Depends(get_session),
):
    """Defer-loaded on-this-day partial — past-year highlights for today's MM-DD."""
    today_mmdd = f"{date.today().month:02d}-{date.today().day:02d}"
    on_this_day = session.exec(
        select(Highlight)
        .options(selectinload(Highlight.book))
        .where(Highlight.user_id == 1)
        .where(Highlight.is_discarded == False)  # noqa: E712
        .where(func.strftime("%m-%d", Highlight.created_at) == today_mmdd)
        .order_by(Highlight.created_at.desc())
        .limit(5)
    ).all()
    return templates.TemplateResponse(
        request, "_dashboard_on_this_day.html",
        {"on_this_day": on_this_day, "today_mmdd": today_mmdd},
    )
