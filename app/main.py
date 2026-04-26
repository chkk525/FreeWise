import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session

from app.db import (
    ensure_schema_migrations,
    get_current_streak,
    get_engine,
    get_settings,
)
from app.models import SQLModel
from app.routers import (
    highlights,
    settings,
    importer,
    library,
    dashboard,
    export,
    api_tokens,
)
from app.api_v2 import router as api_v2_router
from app.services import kindle_import_watcher


_log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create database tables on startup; spin the Kindle import scheduler if configured."""
    os.makedirs("./db", exist_ok=True)
    os.makedirs("./app/static", exist_ok=True)
    os.makedirs("./app/static/uploads/covers", exist_ok=True)
    engine = get_engine()
    SQLModel.metadata.create_all(engine)
    ensure_schema_migrations(engine)

    # Initialize default settings if not exists
    with Session(engine) as session:
        get_settings(session)

    scheduler = _maybe_start_kindle_scheduler()
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


def _maybe_start_kindle_scheduler():
    """Start an APScheduler job that polls KINDLE_IMPORTS_DIR for new exports.

    Returns the scheduler instance (so the caller can shut it down) or None
    if the feature is disabled. We never crash on startup if the directory
    is missing — the watcher itself logs and returns empty.
    """

    imports_dir = kindle_import_watcher.imports_dir_from_env()
    if imports_dir is None:
        _log.info("Kindle auto-import disabled (KINDLE_IMPORTS_DIR not set).")
        return None
    if not imports_dir.exists():
        _log.warning(
            "Kindle auto-import: KINDLE_IMPORTS_DIR=%s does not exist; scheduler "
            "will start but every tick will no-op until the directory appears.",
            imports_dir,
        )

    interval = kindle_import_watcher.interval_seconds_from_env()
    user_id = kindle_import_watcher.user_id_from_env()

    from apscheduler.schedulers.background import BackgroundScheduler

    def _tick() -> None:
        try:
            with Session(get_engine()) as session:
                result = kindle_import_watcher.scan_and_import(
                    imports_dir=imports_dir, session=session, user_id=user_id
                )
            if result.files_scanned:
                _log.info(
                    "Kindle scheduler tick: scanned=%d imported=%d failed=%d "
                    "books=%d highlights=%d",
                    result.files_scanned,
                    result.files_imported,
                    result.files_failed,
                    result.books_created + result.books_matched,
                    result.highlights_created,
                )
        except Exception:  # noqa: BLE001
            _log.exception("Kindle scheduler tick raised; continuing.")

    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _tick,
        "interval",
        seconds=interval,
        id="kindle_import_watcher",
        next_run_time=None,  # first tick fires after `interval`, not immediately
        replace_existing=True,
    )
    scheduler.start()
    _log.info(
        "Kindle auto-import scheduler started (every %ds, dir=%s, user_id=%d).",
        interval,
        imports_dir,
        user_id,
    )
    return scheduler


app = FastAPI(title="FreeWise", lifespan=lifespan)


_STREAK_BEARING_PATHS: tuple[str, ...] = (
    "/dashboard/",
    "/highlights/ui/",
    "/library/ui",
    "/import/ui",
    "/settings/ui",
    "/",
)


@app.middleware("http")
async def inject_streak(request: Request, call_next):
    """Attach the current review streak to request.state for HTML pages that
    actually display it.

    The streak query touches `reviewsession` and is cheap individually but
    not free at scale (3780 books / 460+ highlights deployments observe
    ~30-50ms per request). Restricting to HTML page handlers — and skipping
    JSON / API / static / preview — keeps the API path zero-allocation
    here. Templates always read `request.state.streak`, so the default of
    0 is safe for non-HTML responses too.
    """
    request.state.streak = 0
    path = request.url.path
    needs_streak = any(path.startswith(p) or path == p for p in _STREAK_BEARING_PATHS)
    if needs_streak:
        try:
            with Session(get_engine()) as s:
                request.state.streak = get_current_streak(s)
        except Exception:
            pass
    return await call_next(request)


# Security HTTP headers (Phase 4 hardening — H9). Cheap defence-in-depth
# layered above Cloudflare Access. Static asset paths get the headers too;
# they're idempotent so caching is unaffected.
_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    # Conservative CSP: app uses inline <script> in api_tokens.html copy
    # button + several htmx data attrs, so we permit 'unsafe-inline' for now.
    # A future tightening pass should add per-script nonces.
    "Content-Security-Policy": (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline'; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'"
    ),
}


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    for k, v in _SECURITY_HEADERS.items():
        response.headers.setdefault(k, v)
    return response


# Rate limiting on the API surface (H8). In-process token-bucket per
# (client_ip, path-prefix). NOT a substitute for Cloudflare's edge rate
# limit — this is the second layer for direct LAN access.
_RATE_LIMIT_BUCKET: dict[tuple[str, str], list[float]] = {}
_RATE_LIMIT_LOCK_API = "/api/v2/"
_RATE_LIMIT_WINDOW_SECONDS = 60
_RATE_LIMIT_MAX_HITS = 60  # 60 req / IP / minute on /api/v2/*


@app.middleware("http")
async def rate_limit_api(request: Request, call_next):
    path = request.url.path
    if not path.startswith(_RATE_LIMIT_LOCK_API):
        return await call_next(request)
    import time
    from fastapi.responses import JSONResponse
    client = (request.client.host if request.client else "unknown", _RATE_LIMIT_LOCK_API)
    now = time.monotonic()
    bucket = _RATE_LIMIT_BUCKET.setdefault(client, [])
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    # Drop expired
    while bucket and bucket[0] < cutoff:
        bucket.pop(0)
    if len(bucket) >= _RATE_LIMIT_MAX_HITS:
        retry_after = max(1, int(_RATE_LIMIT_WINDOW_SECONDS - (now - bucket[0])))
        return JSONResponse(
            {"detail": "Rate limit exceeded"},
            status_code=429,
            headers={"Retry-After": str(retry_after)},
        )
    bucket.append(now)
    return await call_next(request)


# Setup templates and static files
templates = Jinja2Templates(directory="app/templates")
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(dashboard.router)
app.include_router(highlights.router)
app.include_router(settings.router)
app.include_router(importer.router)
app.include_router(library.router)
app.include_router(export.router)
app.include_router(api_tokens.router)
app.include_router(api_v2_router.router)


@app.get("/healthz")
async def healthz():
    """Lightweight liveness + readiness probe.

    No auth — intended for an external monitor or `curl` smoke check.
    Returns counts and a non-fatal Ollama reachability flag so a single
    GET tells you:
      - is the app alive (200 = yes)
      - is the DB reachable (counts present = yes)
      - is the embedding model populated (embedded_pct > 0)
      - is Ollama reachable (ollama.reachable = true/false)

    Never returns 5xx for transient Ollama issues — the daemon being
    down is normal and shouldn't page anyone.
    """
    from sqlmodel import Session, select, func
    from app.db import get_engine
    from app.models import Highlight, Embedding
    from app.services.embeddings import _env_url, _env_model

    engine = get_engine()
    out: dict = {"status": "ok"}
    try:
        with Session(engine) as s:
            total_active = int(s.exec(
                select(func.count(Highlight.id))
                .where(Highlight.is_discarded == False)  # noqa: E712
            ).one() or 0)
            embed_model = _env_model()
            embedded = int(s.exec(
                select(func.count(func.distinct(Embedding.highlight_id)))
                .where(Embedding.model_name == embed_model)
            ).one() or 0)
        out["highlights"] = {
            "active": total_active,
            "embedded": embedded,
            "embedded_pct": round((embedded / total_active * 100) if total_active else 0.0, 1),
        }
        out["embed_model"] = embed_model
    except Exception as e:  # noqa: BLE001
        out["status"] = "degraded"
        out["db_error"] = str(e)

    # Best-effort Ollama check — short timeout so the probe stays cheap.
    ollama_url = _env_url()
    out["ollama"] = {"url": ollama_url, "reachable": False}
    try:
        import httpx
        r = httpx.get(f"{ollama_url}/api/tags", timeout=2.0)
        out["ollama"]["reachable"] = r.status_code < 500
        out["ollama"]["status_code"] = r.status_code
    except Exception:  # noqa: BLE001
        # Ollama down is normal; don't surface a stack trace.
        pass

    return out


@app.get("/sw.js")
async def service_worker():
    """Serve the PWA service worker from root scope.
    
    Must be served with Cache-Control: no-store so browsers always fetch the
    latest version — otherwise SW updates are silently skipped for hours.
    """
    from fastapi.responses import FileResponse
    from fastapi import Response
    response = FileResponse("app/static/sw.js", media_type="application/javascript")
    response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon from root path (browsers always request it here)."""
    from fastapi.responses import FileResponse
    return FileResponse("app/static/favicons/favicon.ico", media_type="image/x-icon")


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Root endpoint redirects to dashboard."""
    return RedirectResponse(url="/dashboard/ui", status_code=302)
