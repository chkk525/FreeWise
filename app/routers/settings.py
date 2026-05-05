import os
import tempfile
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from sqlalchemy import text
from sqlmodel import Session, select, func
from starlette.background import BackgroundTask

from app.db import get_engine, get_session, get_settings
from app.models import Settings, Highlight
from app.template_filters import make_templates

THEME_CYCLE = ("light", "dark", "auto")


router = APIRouter(prefix="/settings", tags=["settings"])
templates = make_templates()


# ============ HTML/HTMX Endpoints ============

_FLASH_MESSAGES = {
    "saved": "Settings saved successfully!",
    "reset": "Library reset — all data has been permanently deleted and settings restored to defaults.",
}


@router.get("/ui", response_class=HTMLResponse)
async def ui_settings(
    request: Request,
    saved: int = 0,
    reset: int = 0,
    session: Session = Depends(get_session),
):
    """Render settings page with form."""
    settings = get_settings(session)
    highlights_count_stmt = select(func.count(Highlight.id))
    highlights_count = session.exec(highlights_count_stmt).one()
    flash = None
    if saved:
        flash = _FLASH_MESSAGES["saved"]
    elif reset:
        flash = _FLASH_MESSAGES["reset"]
    return templates.TemplateResponse(request, "settings.html", {"settings": settings,
        "highlights_count": highlights_count,
        "success_message": flash})


@router.post("/ui")
async def update_settings_ui(
    request: Request,
    daily_review_count: int = Form(...),
    highlight_recency: int = Form(...),
    theme: str = Form(...),
    session: Session = Depends(get_session),
):
    """Update settings, then redirect (PRG) so a refresh doesn't re-submit."""
    settings = get_settings(session)

    settings.daily_review_count = max(1, min(15, daily_review_count))
    settings.highlight_recency = max(0, min(10, highlight_recency))
    settings.theme = theme

    session.add(settings)
    session.commit()

    return RedirectResponse(url="/settings/ui?saved=1", status_code=303)


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


@router.post("/reset-library")
async def reset_library(request: Request):
    """Drop + recreate every table, then PRG-redirect to /settings/ui."""
    from sqlmodel import SQLModel, Session
    from app.db import get_engine

    engine = get_engine()
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        get_settings(s)  # ensure default row exists post-reset

    return RedirectResponse(url="/settings/ui?reset=1", status_code=303)


@router.post("/backup.db")
async def download_backup():
    """Stream a consistent SQLite snapshot of the live DB.

    Uses ``VACUUM INTO`` so the snapshot is self-contained and points at
    a freshly compacted copy. In SQLite's default rollback-journal mode
    this acquires an exclusive lock for the duration — readers and
    writers block until the snapshot completes, which on multi-GB DBs
    can take seconds. WAL mode would let readers continue, but we leave
    journal mode untouched here since the rest of the app expects it.

    Backed by POST (not GET) so browser prefetchers, link crawlers, and
    favicon scrapers can't accidentally trigger an exclusive-lock
    snapshot. The settings UI button posts via a tiny JS form.

    Snapshot file is created inside an isolated temp directory to avoid
    a TOCTOU race against /tmp; cleaned up via BackgroundTask after the
    FileResponse finishes streaming.
    """
    engine = get_engine()
    if engine.url.drivername != "sqlite":
        # The whole point of this endpoint is a single-file snapshot —
        # bail loudly rather than producing something misleading on a
        # non-SQLite backend.
        raise HTTPException(
            status_code=501,
            detail="Backup is only supported on SQLite databases.",
        )

    # Private temp dir prevents another process from racing into the
    # path between an unlink + VACUUM INTO. The dir + file are removed
    # by BackgroundTask once the response finishes.
    tmp_dir = tempfile.mkdtemp(prefix="freewise-backup-")
    tmp_path = os.path.join(tmp_dir, "snapshot.db")

    # tmp_path comes from mkdtemp + a constant filename — never user
    # input — so the f-string interpolation can't be SQL-injected. Guard
    # belt-and-braces against a future refactor introducing a quote.
    if "'" in tmp_path:
        raise HTTPException(status_code=500, detail="Unsafe temp path.")

    with engine.begin() as conn:
        conn.execute(text(f"VACUUM INTO '{tmp_path}'"))

    fname = f"freewise-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"
    return FileResponse(
        tmp_path,
        media_type="application/vnd.sqlite3",
        filename=fname,
        background=BackgroundTask(_cleanup_backup_dir, tmp_dir),
    )


def _cleanup_backup_dir(path: str) -> None:
    """Best-effort temp-dir cleanup that never raises into the response cycle."""
    try:
        # The dir contains exactly one file (snapshot.db). Remove both.
        for entry in os.listdir(path):
            try:
                os.unlink(os.path.join(path, entry))
            except OSError:
                pass
        os.rmdir(path)
    except FileNotFoundError:
        pass
    except OSError:
        # Snapshot has already been delivered; cleanup failure is benign.
        pass
