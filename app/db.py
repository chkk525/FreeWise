import os
from sqlmodel import create_engine, SQLModel, Session, select

# Module-level engine singleton — created once when the module is first imported.
_engine = create_engine(
    os.getenv("FREEWISE_DB_URL", "sqlite:///./db/freewise.db"),
    echo=False,
    connect_args={"check_same_thread": False},
)


def get_engine():
    """Return the module-level SQLAlchemy engine singleton."""
    return _engine


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
