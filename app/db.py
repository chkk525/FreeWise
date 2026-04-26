import logging
import os
from sqlalchemy import text
from sqlmodel import create_engine, SQLModel, Session, select

# Module-level engine singleton — created once when the module is first imported.
_engine = create_engine(
    os.getenv("FREEWISE_DB_URL", "sqlite:///./db/freewise.db"),
    echo=False,
    connect_args={"check_same_thread": False},
)

_log = logging.getLogger(__name__)


def get_engine():
    """Return the module-level SQLAlchemy engine singleton."""
    return _engine


def ensure_schema_migrations(engine=None) -> None:
    """Apply lightweight forward-only schema migrations.

    SQLite + a single-user app means we can get away with a tiny ALTER TABLE
    helper instead of a full alembic dependency. Each migration:
    - Inspects PRAGMA table_info(book) to find missing columns
    - Adds them with ADD COLUMN if absent
    - Backfills from existing data where it makes sense

    Called once during the FastAPI lifespan, immediately after
    ``SQLModel.metadata.create_all`` so brand-new DBs get the column from
    the model definition AND existing DBs get the column added in place.

    Idempotent: re-running on an already-migrated DB is a no-op.
    """
    engine = engine or _engine
    with engine.begin() as conn:
        cols = {row[1] for row in conn.execute(text("PRAGMA table_info(book)")).all()}
        if "kindle_asin" not in cols:
            _log.info("migration: adding book.kindle_asin column")
            conn.execute(text("ALTER TABLE book ADD COLUMN kindle_asin VARCHAR"))
            conn.execute(
                text("CREATE INDEX IF NOT EXISTS ix_book_kindle_asin ON book (kindle_asin)")
            )
            # Backfill from document_tags entries shaped `asin:<value>`.
            rows = conn.execute(
                text("SELECT id, document_tags FROM book WHERE document_tags LIKE '%asin:%'")
            ).all()
            backfilled = 0
            for row_id, tags in rows:
                for tag in (tags or "").split(","):
                    t = tag.strip()
                    if t.startswith("asin:") and len(t) > 5:
                        asin = t[5:]
                        conn.execute(
                            text("UPDATE book SET kindle_asin = :a WHERE id = :id AND kindle_asin IS NULL"),
                            {"a": asin, "id": row_id},
                        )
                        backfilled += 1
                        break
            if backfilled:
                _log.info("migration: backfilled kindle_asin on %d book rows", backfilled)

        # ── ApiToken hashed-storage migration (security) ────────────────
        token_cols = {
            row[1] for row in conn.execute(text("PRAGMA table_info(apitoken)")).all()
        }
        if token_cols and "token_prefix" not in token_cols:
            _log.info("migration: adding apitoken.token_prefix + token_hash columns")
            conn.execute(text("ALTER TABLE apitoken ADD COLUMN token_prefix VARCHAR"))
            conn.execute(text("ALTER TABLE apitoken ADD COLUMN token_hash VARCHAR"))
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_apitoken_token_prefix "
                    "ON apitoken (token_prefix)"
                )
            )
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_apitoken_token_hash "
                    "ON apitoken (token_hash)"
                )
            )
            # Backfill: hash existing plaintext tokens so we can stop reading
            # the plaintext column going forward. The plaintext column is
            # left in place for one transition window so an in-flight client
            # is not broken by the deploy.
            import hashlib
            rows = conn.execute(
                text("SELECT id, token FROM apitoken WHERE token IS NOT NULL")
            ).all()
            for row_id, raw in rows:
                if not raw:
                    continue
                h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
                prefix = raw[:16]  # first 16 chars; safe to display
                conn.execute(
                    text(
                        "UPDATE apitoken SET token_prefix = :p, token_hash = :h "
                        "WHERE id = :id AND token_hash IS NULL"
                    ),
                    {"p": prefix, "h": h, "id": row_id},
                )
            if rows:
                _log.info(
                    "migration: hashed %d pre-existing apitoken row(s)", len(rows)
                )

        # ── Composite index for the review-pool hot query (perf H6) ──────
        # The query
        #   WHERE is_discarded = FALSE AND highlight_weight > 0
        #   ORDER BY RANDOM() LIMIT 1000
        # fires on every cold review page. SQLite uses at most one index
        # per table scan; the existing single-column indexes (is_discarded,
        # highlight_weight) can't both be used together. A composite index
        # over both columns lets the planner skip the full scan.
        existing_tables = {
            row[0]
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).all()
        }
        if "highlight" in existing_tables:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_highlight_review_pool "
                    "ON highlight (is_discarded, highlight_weight)"
                )
            )

        # ── ReviewSession.session_uuid lookup index (perf H7) ────────────
        # SQLModel emits the index on fresh DBs via `unique=True`, but
        # ALTER TABLE pre-existing schemas may not have picked it up. The
        # /highlights/ui/review handler reads the row by uuid on every
        # cookie-bearing request.
        if "reviewsession" in existing_tables:
            conn.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_reviewsession_session_uuid "
                    "ON reviewsession (session_uuid)"
                )
            )


def get_session():
    """FastAPI dependency that yields a database session."""
    with Session(_engine) as session:
        yield session


def get_settings(session: Session):
    """Return the single Settings record, creating defaults if absent."""
    from app.models import Settings
    settings = session.exec(select(Settings)).first()
    if not settings:
        settings = Settings()
        session.add(settings)
        session.commit()
        session.refresh(settings)
    if settings.highlight_recency is None:
        settings.highlight_recency = 5
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


_STREAK_LOOKBACK_DAYS = 400  # Largest plausible streak; cheap insurance.


def get_current_streak(session: Session) -> int:
    """Return the current consecutive-day review streak (0 if no active streak).

    A streak is alive if a completed session exists for today or yesterday.
    Multiple sessions on the same calendar day count as one streak day.

    Performance (Phase 4): only the distinct ``session_date`` values from the
    last ``_STREAK_LOOKBACK_DAYS`` are pulled. The previous implementation
    loaded every completed ReviewSession (1 row/day = ~365/year) into Python
    and called this from middleware on every HTML page hit. The new query is
    one indexed range scan + DISTINCT.
    """
    from app.models import ReviewSession
    from datetime import date, timedelta

    today = date.today()
    earliest = today - timedelta(days=_STREAK_LOOKBACK_DAYS)

    # SQL-side DISTINCT on session_date so no per-row hydration. The
    # is_completed predicate uses the same combined index range scan as
    # the existing single-column index.
    stmt = (
        select(ReviewSession.session_date)
        .where(ReviewSession.is_completed == True)  # noqa: E712 (SQLAlchemy idiom)
        .where(ReviewSession.session_date >= earliest)
        .distinct()
        .order_by(ReviewSession.session_date.desc())
    )
    sorted_dates = list(session.exec(stmt).all())

    if not sorted_dates:
        return 0

    yesterday = today - timedelta(days=1)
    if sorted_dates[0] < yesterday:
        return 0

    streak = 1
    check_date = sorted_dates[0] - timedelta(days=1)
    for d in sorted_dates[1:]:
        if d == check_date:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            break
    return streak
