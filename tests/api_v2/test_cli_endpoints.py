"""Integration tests for the CLI-supporting /api/v2 endpoints.

Covers:
- GET  /api/v2/highlights/search
- GET  /api/v2/highlights/{id}
- PATCH /api/v2/highlights/{id}
- GET  /api/v2/stats
"""

from __future__ import annotations

import hashlib

from app.models import ApiToken


def _auth_headers(db, value: str = "tk") -> dict[str, str]:
    db.add(
        ApiToken(
            token_prefix=value[:16],
            token_hash=hashlib.sha256(value.encode()).hexdigest(),
            name="cli-test",
            user_id=1,
        )
    )
    db.commit()
    return {"Authorization": f"Token {value}"}


# ── GET /api/v2/highlights/search ────────────────────────────────────────────


def test_search_matches_text(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="The quick brown fox jumps")
    make_highlight(text="Unrelated row")
    resp = client.get(
        "/api/v2/highlights/search",
        headers=headers,
        params={"q": "brown fox"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["text"] == "The quick brown fox jumps"


def test_search_matches_note(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="Plain", note="A unique-marker in the note")
    make_highlight(text="Other", note="nothing")
    resp = client.get(
        "/api/v2/highlights/search",
        headers=headers,
        params={"q": "unique-marker"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 1


def test_search_excludes_discarded_by_default(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="needle in active")
    make_highlight(text="needle in discarded", is_discarded=True)
    resp = client.get(
        "/api/v2/highlights/search", headers=headers, params={"q": "needle"}
    )
    assert resp.json()["count"] == 1


def test_search_include_discarded(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="needle a")
    make_highlight(text="needle b", is_discarded=True)
    resp = client.get(
        "/api/v2/highlights/search",
        headers=headers,
        params={"q": "needle", "include_discarded": "true"},
    )
    assert resp.json()["count"] == 2


def test_search_escapes_like_wildcards(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="50% off literal percent")
    make_highlight(text="completely unrelated")
    resp = client.get(
        "/api/v2/highlights/search", headers=headers, params={"q": "%"}
    )
    body = resp.json()
    assert body["count"] == 1
    assert "50% off" in body["results"][0]["text"]


def test_search_requires_auth(client, db, make_highlight):
    make_highlight(text="anything")
    resp = client.get("/api/v2/highlights/search", params={"q": "anything"})
    assert resp.status_code == 401


# ── GET /api/v2/highlights/{id} ──────────────────────────────────────────────


def test_get_highlight(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="Detail me", note="A note")
    resp = client.get(f"/api/v2/highlights/{h.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == h.id
    assert body["text"] == "Detail me"
    assert body["note"] == "A note"
    assert body["is_favorited"] is False
    assert body["is_discarded"] is False


def test_get_highlight_404_for_missing(client, db):
    headers = _auth_headers(db)
    resp = client.get("/api/v2/highlights/9999", headers=headers)
    assert resp.status_code == 404


def test_get_highlight_404_for_other_user(client, db, make_highlight):
    """A token for user 1 must not see a highlight belonging to user 2."""
    h = make_highlight(text="not yours")
    h.user_id = 2  # forcibly reassign
    db.add(h)
    db.commit()
    headers = _auth_headers(db)
    resp = client.get(f"/api/v2/highlights/{h.id}", headers=headers)
    assert resp.status_code == 404


# ── PATCH /api/v2/highlights/{id} ────────────────────────────────────────────


def test_patch_updates_note(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    resp = client.patch(
        f"/api/v2/highlights/{h.id}",
        headers=headers,
        json={"note": "fresh note"},
    )
    assert resp.status_code == 200
    assert resp.json()["note"] == "fresh note"


def test_patch_clears_note(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", note="old")
    resp = client.patch(
        f"/api/v2/highlights/{h.id}", headers=headers, json={"note": ""}
    )
    assert resp.status_code == 200
    assert resp.json()["note"] == ""


def test_patch_toggles_favorite(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r1 = client.patch(
        f"/api/v2/highlights/{h.id}", headers=headers, json={"is_favorited": True}
    )
    assert r1.status_code == 200
    assert r1.json()["is_favorited"] is True


def test_patch_discard_auto_unfavorites(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", is_favorited=True)
    resp = client.patch(
        f"/api/v2/highlights/{h.id}",
        headers=headers,
        json={"is_discarded": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_discarded"] is True
    assert body["is_favorited"] is False


def test_patch_rejects_favoriting_discarded(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", is_discarded=True)
    resp = client.patch(
        f"/api/v2/highlights/{h.id}",
        headers=headers,
        json={"is_favorited": True},
    )
    assert resp.status_code == 400


# ── GET /api/v2/stats ────────────────────────────────────────────────────────


def test_stats_returns_counts(client, db, make_highlight, make_book):
    headers = _auth_headers(db)
    book = make_book(title="B")
    make_highlight(text="a", book=book)
    make_highlight(text="b", book=book, is_favorited=True)
    make_highlight(text="c", book=book, is_discarded=True)
    resp = client.get("/api/v2/stats", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["highlights_total"] == 3
    assert body["highlights_active"] == 2
    assert body["highlights_discarded"] == 1
    assert body["highlights_favorited"] == 1
    assert body["books_total"] == 1
    # Two active highlights with NULL next_review are due.
    assert body["review_due_today"] == 2
