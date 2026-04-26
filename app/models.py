from datetime import datetime, date, UTC
from typing import Optional
from sqlmodel import SQLModel, Field, Relationship


class User(SQLModel, table=True):
    # TODO: implement auth
    """User model for single-user or multi-user setup."""
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    email_send_time: Optional[str] = None  # "HH:MM" local time
    
    def __repr__(self) -> str:
        return f"User(id={self.id}, email={self.email})"


class ApiToken(SQLModel, table=True):
    """API token for programmatic access (Readwise-compatible API).

    Storage model (Phase 4 hardening):
      * The raw token is shown to the user EXACTLY ONCE at creation and
        never persisted. It has the shape ``fw_<24-byte-hex-prefix><32-byte-hex-secret>``
        so the prefix is human-recognisable and the secret part is the
        cryptographically-relevant material.
      * ``token_prefix`` is the public-display prefix (16 hex chars / 8 bytes).
        Indexed for cheap lookup; safe to log.
      * ``token_hash`` is a sha256 hash of the full raw token. Compared in
        constant time. Never logged.
      * ``token`` (legacy column) holds the plaintext token for any rows
        created before the migration. New rows leave it NULL. Lookup falls
        back to it only when token_hash misses, then opportunistically
        upgrades the row to hash storage on first use.
    """
    id: Optional[int] = Field(default=None, primary_key=True)
    token: Optional[str] = Field(default=None, index=True, unique=False)
    token_prefix: Optional[str] = Field(default=None, index=True)
    token_hash: Optional[str] = Field(default=None, index=True)
    name: str  # human label, e.g. "chrome-extension-laptop"
    user_id: int = Field(foreign_key="user.id", index=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None), index=True)
    last_used_at: Optional[datetime] = Field(default=None, index=True)

    def __repr__(self) -> str:
        return f"ApiToken(id={self.id}, name={self.name!r})"


class Book(SQLModel, table=True):
    """Book model for organizing highlights by source."""
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str = Field(index=True)
    author: Optional[str] = Field(default=None, index=True)
    document_tags: Optional[str] = None  # comma-separated tags
    review_weight: float = Field(default=1.0, index=True)  # 0.0 (Never) to 2.0 (More)
    cover_image_url: Optional[str] = Field(default=None)
    cover_image_source: Optional[str] = Field(default=None)
    # Kindle ASIN. Used as the primary dedup key for Kindle imports — survives
    # title rewrites in Amazon's library. Backfilled from `document_tags` on
    # startup; see app.db.ensure_schema_migrations.
    kindle_asin: Optional[str] = Field(default=None, index=True)
    highlights: list["Highlight"] = Relationship(back_populates="book")
    
    def __repr__(self) -> str:
        author_str = f" by {self.author}" if self.author else ""
        return f"Book(id={self.id}, title='{self.title}'{author_str})"


class Highlight(SQLModel, table=True):
    """Highlight model for storing text excerpts with review scheduling."""
    id: Optional[int] = Field(default=None, primary_key=True)
    text: str = Field(index=True)
    note: Optional[str] = None  # Additional notes or annotations
    book_id: Optional[int] = Field(default=None, foreign_key="book.id", index=True)
    created_at: Optional[datetime] = Field(default=None, index=True)  # When the highlight was made (None if unknown)
    location_type: Optional[str] = Field(default=None)  # "page" or "order" from Readwise
    location: Optional[int] = Field(default=None, index=True)  # Page number or order in book
    is_favorited: bool = Field(default=False, index=True)
    is_discarded: bool = Field(default=False, index=True)
    next_review: Optional[datetime] = Field(default=None, index=True)
    last_reviewed_at: Optional[datetime] = Field(default=None, index=True)
    review_count: int = Field(default=0)
    highlight_weight: float = Field(default=1.0, index=True)  # 0.0 (Never) to 2.0 (More)
    user_id: int = Field(foreign_key="user.id", index=True)
    book: Optional["Book"] = Relationship(back_populates="highlights")
    
    def __repr__(self) -> str:
        preview = self.text[:50] + "..." if len(self.text) > 50 else self.text
        return f"Highlight(id={self.id}, text='{preview}')"


class Tag(SQLModel, table=True):
    """Tag model for organizing highlights."""
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    
    def __repr__(self) -> str:
        return f"Tag(id={self.id}, name={self.name})"


class HighlightTag(SQLModel, table=True):
    # TODO: add highlight-level tag UI
    """Many-to-many relationship between highlights and tags."""
    highlight_id: int = Field(foreign_key="highlight.id", primary_key=True)
    tag_id: int = Field(foreign_key="tag.id", primary_key=True)


class Settings(SQLModel, table=True):
    """Application settings for customizing behavior."""
    id: Optional[int] = Field(default=None, primary_key=True)
    daily_review_count: int = Field(default=5)
    highlight_recency: int = Field(default=5)  # 0=prefer older, 5=neutral, 10=prefer newer
    theme: str = Field(default="light")
    
    def __repr__(self) -> str:
        return f"Settings(id={self.id}, daily_review_count={self.daily_review_count}, highlight_recency={self.highlight_recency})"


class ReviewSession(SQLModel, table=True):
    """Log of daily review sessions for tracking activity and engagement."""
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    session_uuid: str = Field(index=True, unique=True)  # UUID for tracking across requests
    started_at: datetime = Field(index=True)
    completed_at: Optional[datetime] = Field(default=None, index=True)
    session_date: date = Field(index=True)  # Date of session for easy querying
    target_count: int = Field(default=5)  # Number of highlights intended to review
    highlights_reviewed: int = Field(default=0)  # Highlights marked "Done"
    highlights_discarded: int = Field(default=0)  # Highlights discarded in session
    highlights_favorited: int = Field(default=0)  # Highlights favorited in session
    is_completed: bool = Field(default=False, index=True)  # Whether user finished the session
    
    def __repr__(self) -> str:
        return f"ReviewSession(id={self.id}, date={self.session_date}, reviewed={self.highlights_reviewed}/{self.target_count})"
