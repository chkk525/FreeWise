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

        tables = {
            row[0]
            for row in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).all()
        }
        if "apitoken" in tables:
            cols = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(apitoken)")).all()
            }
            if "scopes" not in cols:
                _log.info("migration: adding apitoken.scopes column")
                conn.execute(text("ALTER TABLE apitoken ADD COLUMN scopes VARCHAR"))


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


def get_current_streak(session: Session) -> int:
    """Return the current consecutive-day review streak (0 if no active streak).

    A streak is alive if a completed session exists for today or yesterday.
    Multiple sessions on the same calendar day count as one streak day.
    """
    from app.models import ReviewSession
    from datetime import date, timedelta

    today = date.today()
    completed_stmt = select(ReviewSession).where(ReviewSession.is_completed == True)
    completed_sessions = session.exec(completed_stmt).all()

    if not completed_sessions:
        return 0

    # Deduplicate: multiple sessions on the same day count as one streak day
    sorted_dates = sorted({rs.session_date for rs in completed_sessions}, reverse=True)
    yesterday = today - timedelta(days=1)

    # Streak must start from today or yesterday to be "current"
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
