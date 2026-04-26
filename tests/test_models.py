"""
Tests for database models, default values, constraints, and relationships.
"""
import pytest
from datetime import datetime, date
from sqlmodel import Session, select

from app.models import User, Book, Highlight, Settings, Tag, HighlightTag, ReviewSession


class TestBookModel:
    """Book model field defaults and relationships."""

    def test_defaults(self, db, make_book):
        book = make_book(title="Sapiens", author="Yuval Noah Harari")
        assert book.id is not None
        assert book.title == "Sapiens"
        assert book.author == "Yuval Noah Harari"
        assert book.review_weight == 1.0
        assert book.cover_image_url is None
        assert book.cover_image_source is None
        assert book.document_tags is None

    def test_no_author(self, db, make_book):
        book = make_book(title="Anonymous", author=None)
        assert book.author is None

    def test_review_weight_range(self, db, make_book):
        b0 = make_book(title="Never", review_weight=0.0)
        b2 = make_book(title="More", review_weight=2.0)
        assert b0.review_weight == 0.0
        assert b2.review_weight == 2.0


class TestHighlightModel:
    """Highlight model field defaults and constraints."""

    def test_defaults(self, db, make_highlight):
        h = make_highlight(text="To be or not to be")
        assert h.id is not None
        assert h.text == "To be or not to be"
        assert h.highlight_weight == 1.0
        assert h.is_favorited is False
        assert h.is_discarded is False
        assert h.review_count == 0
        assert h.note is None
        assert h.location is None
        assert h.location_type is None

    def test_book_relationship(self, db, make_book, make_highlight):
        book = make_book(title="Related Book")
        h = make_highlight(text="Linked", book=book)
        assert h.book_id == book.id
        db.refresh(h)
        assert h.book is not None
        assert h.book.title == "Related Book"

    def test_favorited_flag(self, db, make_highlight):
        h = make_highlight(is_favorited=True)
        assert h.is_favorited is True

    def test_discarded_flag(self, db, make_highlight):
        h = make_highlight(is_discarded=True)
        assert h.is_discarded is True


class TestSettingsModel:
    """Settings model defaults and field values."""

    def test_defaults_from_db(self, db):
        settings = db.exec(select(Settings)).first()
        assert settings is not None
        assert settings.daily_review_count == 5
        assert settings.highlight_recency == 5
        assert settings.theme == "light"


class TestReviewSessionModel:
    """ReviewSession model fields."""

    def test_creation(self, db, make_review_session):
        rs = make_review_session(
            highlights_reviewed=3,
            highlights_discarded=1,
            highlights_favorited=1,
            is_completed=True,
        )
        assert rs.id is not None
        assert rs.highlights_reviewed == 3
        assert rs.highlights_discarded == 1
        assert rs.highlights_favorited == 1
        assert rs.is_completed is True
        assert rs.session_date == date.today()

    def test_incomplete_session(self, db, make_review_session):
        rs = make_review_session(is_completed=False, completed_at=None)
        assert rs.is_completed is False


class TestTagModel:
    """Tag and HighlightTag many-to-many relationship."""

    def test_tag_creation(self, db):
        tag = Tag(name="philosophy")
        db.add(tag)
        db.commit()
        db.refresh(tag)
        assert tag.id is not None
        assert tag.name == "philosophy"

    def test_highlight_tag_link(self, db, make_highlight):
        h = make_highlight(text="Tagged highlight")
        tag = Tag(name="science")
        db.add(tag)
        db.commit()
        db.refresh(tag)

        link = HighlightTag(highlight_id=h.id, tag_id=tag.id)
        db.add(link)
        db.commit()

        # Query back
        found = db.exec(
            select(HighlightTag).where(HighlightTag.highlight_id == h.id)
        ).first()
        assert found is not None
        assert found.tag_id == tag.id


class TestApiToken:
    def test_create_api_token(self, db):
        from app.models import ApiToken
        token = ApiToken(
            token="freewise_abc123def456",
            name="chrome-extension-laptop",
            user_id=1,
        )
        db.add(token)
        db.commit()
        db.refresh(token)

        assert token.id is not None
        assert token.token == "freewise_abc123def456"
        assert token.created_at is not None  # auto-set by default

    def test_api_token_unique(self, db):
        """Phase 4 (security hardening): uniqueness moved off the legacy
        plaintext column. The canonical lookup is now (token_prefix,
        token_hash). The legacy ``token`` column is kept only for the
        in-place migration window and is no longer constrained."""
        from app.models import ApiToken
        db.add(ApiToken(token="dup", name="a", user_id=1))
        db.commit()
        db.add(ApiToken(token="dup", name="b", user_id=1))
        db.commit()  # no IntegrityError post-Phase-4
        from sqlmodel import select
        rows = db.exec(select(ApiToken).where(ApiToken.token == "dup")).all()
        assert len(rows) == 2
