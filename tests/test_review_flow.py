"""
Tests for the HTML review session flow:
  start review → advance through cards → session complete.
"""
from datetime import date
from sqlmodel import select

from app.models import ReviewSession, Highlight


class TestStartReview:
    """GET /highlights/ui/review — starts or resumes a review session."""

    def test_start_creates_session(self, client, make_highlight):
        make_highlight(text="H1")
        make_highlight(text="H2")
        resp = client.get("/highlights/ui/review")
        assert resp.status_code == 200
        # Should set the session cookie
        assert "review_session_id" in resp.cookies

    def test_start_no_highlights(self, client):
        """When pool is empty the page still renders (zero-card session)."""
        resp = client.get("/highlights/ui/review")
        assert resp.status_code == 200

    def test_start_creates_db_record(self, client, db, make_highlight):
        make_highlight(text="H1")
        client.get("/highlights/ui/review")
        rs = db.exec(select(ReviewSession)).first()
        assert rs is not None
        assert rs.is_completed is False
        assert rs.session_date == date.today()

    def test_reset_creates_new_session(self, client, make_highlight):
        make_highlight(text="H1")
        r1 = client.get("/highlights/ui/review")
        cookie1 = r1.cookies.get("review_session_id")
        r2 = client.get("/highlights/ui/review?reset=true")
        cookie2 = r2.cookies.get("review_session_id")
        assert cookie2 is not None
        assert cookie1 != cookie2


class TestAdvanceReview:
    """POST /highlights/ui/review/next — advance through the queue."""

    def _start_session(self, client):
        """Helper: start a review and return the session cookie value."""
        resp = client.get("/highlights/ui/review")
        return resp.cookies.get("review_session_id")

    def test_next_updates_review_count(self, client, db, make_highlight):
        h = make_highlight(text="H1")
        session_id = self._start_session(client)
        client.cookies.set("review_session_id", session_id)
        client.post("/highlights/ui/review/next", data={"current_id": str(h.id)})
        db.expire_all()
        updated = db.get(Highlight, h.id)
        assert updated.review_count == 1
        assert updated.last_reviewed_at is not None

    def test_next_increments_highlights_reviewed(self, client, db, make_highlight):
        h = make_highlight(text="H1")
        session_id = self._start_session(client)
        client.cookies.set("review_session_id", session_id)
        client.post("/highlights/ui/review/next", data={"current_id": str(h.id)})
        db.expire_all()
        rs = db.exec(
            select(ReviewSession).where(ReviewSession.session_uuid == session_id)
        ).first()
        assert rs is not None
        assert rs.highlights_reviewed >= 1


class TestSessionCompletion:
    """Walking through all cards marks the session complete."""

    def test_complete_session(self, client, db, make_highlight):
        """With daily_review_count=5 but only 1 highlight, session should
        complete after one 'next'."""
        h = make_highlight(text="Solo")
        session_id = client.get("/highlights/ui/review").cookies.get(
            "review_session_id"
        )
        client.cookies.set("review_session_id", session_id)
        resp = client.post(
            "/highlights/ui/review/next", data={"current_id": str(h.id)}
        )
        assert resp.status_code == 200
        # Should render the completion template
        db.expire_all()
        rs = db.exec(
            select(ReviewSession).where(ReviewSession.session_uuid == session_id)
        ).first()
        # Session should be marked complete
        if rs:
            assert rs.is_completed is True
            assert rs.completed_at is not None


class TestSessionExpiry:
    """When no valid session exists, fallback renders gracefully."""

    def test_next_without_session_cookie(self, client, make_highlight):
        h = make_highlight(text="H1")
        # Post without a session cookie
        resp = client.post(
            "/highlights/ui/review/next", data={"current_id": str(h.id)}
        )
        # Should not crash — returns session-expired template or similar
        assert resp.status_code == 200

    def test_next_with_invalid_cookie(self, client, make_highlight):
        h = make_highlight(text="H1")
        client.cookies.set("review_session_id", "bogus-uuid")
        resp = client.post(
            "/highlights/ui/review/next", data={"current_id": str(h.id)}
        )
        assert resp.status_code == 200
