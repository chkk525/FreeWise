"""Tests for app.services.review_log + GET /api/v2/review-log."""
from __future__ import annotations

from datetime import date, datetime, timedelta, UTC

from sqlmodel import select

from app.models import ApiToken, Highlight, ReviewLog
from app.services.review_log import (
    counts_by_day,
    install_listener,
    recent_entries,
)


def _seed_token(db) -> str:
    raw = "review-log-token"
    import hashlib
    db.add(
        ApiToken(
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            token_prefix=raw[:16],
            name="rl",
            user_id=1,
            scopes="kindle:import,highlights:read,highlights:write,books:read",
        )
    )
    db.commit()
    return raw


# ── Listener: which mutations log ─────────────────────────────────────────


def test_listener_logs_favorite_transition(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True
    db.add(h)
    db.commit()
    rows = db.exec(select(ReviewLog)).all()
    assert [(r.highlight_id, r.action) for r in rows] == [(h.id, "favorite")]


def test_listener_logs_unfavorite(db, make_highlight):
    install_listener()
    h = make_highlight(text="x", is_favorited=True)
    h.is_favorited = False
    db.add(h)
    db.commit()
    rows = db.exec(select(ReviewLog).where(ReviewLog.action == "unfavorite")).all()
    assert len(rows) == 1
    assert rows[0].highlight_id == h.id


def test_listener_logs_discard_and_restore(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_discarded = True
    db.add(h)
    db.commit()
    db.refresh(h)  # mimic the route pattern (fresh session.get per request)
    h.is_discarded = False
    db.add(h)
    db.commit()
    actions = [r.action for r in db.exec(select(ReviewLog).order_by(ReviewLog.id.asc())).all()]
    assert actions == ["discard", "restore"]


def test_listener_logs_master_and_unmaster(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_mastered = True
    db.add(h); db.commit()
    db.refresh(h)
    h.is_mastered = False
    db.add(h); db.commit()
    actions = [r.action for r in db.exec(select(ReviewLog).order_by(ReviewLog.id.asc())).all()]
    assert actions == ["master", "unmaster"]


def test_listener_logs_done_when_last_reviewed_at_bumped(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.last_reviewed_at = datetime.now(UTC).replace(tzinfo=None)
    h.review_count = 1
    db.add(h)
    db.commit()
    rows = db.exec(select(ReviewLog).where(ReviewLog.action == "done")).all()
    assert len(rows) == 1


def test_listener_does_not_log_on_fresh_insert(db, make_highlight):
    install_listener()
    # Creating a highlight with is_favorited=True from the start must NOT
    # produce a `favorite` log entry — it's just the initial state.
    h = make_highlight(text="x", is_favorited=True)
    rows = db.exec(select(ReviewLog).where(ReviewLog.highlight_id == h.id)).all()
    assert rows == []


def test_listener_idempotent_install():
    install_listener()
    install_listener()
    install_listener()
    # No exception, single registration enforced via module flag.


# ── Read helpers ──────────────────────────────────────────────────────────


def test_recent_entries_filters_by_action(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    db.refresh(h)
    h.is_discarded = True; db.add(h); db.commit()
    rows = recent_entries(db, actions=["discard"])
    assert [r.action for r in rows] == ["discard"]


def test_recent_entries_respects_since_cutoff(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    cutoff = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=1)
    rows = recent_entries(db, since=cutoff)
    assert rows == []


def test_counts_by_day_returns_dense_window(db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    counts = counts_by_day(db, days=7)
    assert len(counts) == 7
    days, totals = zip(*counts)
    assert all(isinstance(d, date) for d in days)
    assert sum(totals) == 1


# ── HTTP API ──────────────────────────────────────────────────────────────


def test_review_log_endpoint_returns_recent_entries(client, db, make_highlight):
    install_listener()
    raw = _seed_token(db)
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    db.refresh(h)
    h.is_discarded = True; db.add(h); db.commit()
    resp = client.get(
        "/api/v2/review-log",
        headers={"Authorization": f"Token {raw}"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["count"] == 2
    actions = [e["action"] for e in data["results"]]
    # Newest first.
    assert actions == ["discard", "favorite"]


def test_review_log_endpoint_action_filter(client, db, make_highlight):
    install_listener()
    raw = _seed_token(db)
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    db.refresh(h)
    h.is_discarded = True; db.add(h); db.commit()
    resp = client.get(
        "/api/v2/review-log?action=discard",
        headers={"Authorization": f"Token {raw}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["action"] == "discard"


def test_review_log_endpoint_requires_auth(client):
    resp = client.get("/api/v2/review-log")
    assert resp.status_code == 401


# ── Dashboard widget ──────────────────────────────────────────────────────


def test_dashboard_renders_seven_day_activity_widget(client, db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Past 7 days" in resp.text
    assert "1 action" in resp.text  # singular


def test_dashboard_widget_singular_vs_plural(client, db, make_highlight):
    install_listener()
    h = make_highlight(text="x")
    h.is_favorited = True; db.add(h); db.commit()
    db.refresh(h)
    h.is_discarded = True; db.add(h); db.commit()
    resp = client.get("/")
    assert "2 actions" in resp.text  # plural
