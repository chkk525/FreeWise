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


def test_random_returns_one_highlight(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="alpha")
    make_highlight(text="beta")
    r = client.get("/api/v2/highlights/random", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] in ("alpha", "beta")


def test_random_404_when_empty(client, db):
    headers = _auth_headers(db)
    r = client.get("/api/v2/highlights/random", headers=headers)
    assert r.status_code == 404


def test_random_excludes_discarded_by_default(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="alive")
    make_highlight(text="trashed", is_discarded=True)
    # Run a few times to make it likely we'd hit the discarded one if filter broke.
    for _ in range(10):
        r = client.get("/api/v2/highlights/random", headers=headers)
        assert r.json()["text"] == "alive"


def test_random_book_id_filter(client, db, make_highlight, make_book):
    headers = _auth_headers(db)
    b1 = make_book(title="A")
    b2 = make_book(title="B")
    make_highlight(text="from a", book=b1)
    make_highlight(text="from b", book=b2)
    for _ in range(8):
        r = client.get(
            "/api/v2/highlights/random", headers=headers,
            params={"book_id": b1.id},
        )
        assert r.json()["text"] == "from a"


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


def test_patch_toggles_mastered(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.patch(
        f"/api/v2/highlights/{h.id}", headers=headers, json={"is_mastered": True},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_mastered"] is True


def test_patch_rejects_mastering_discarded(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", is_discarded=True)
    r = client.patch(
        f"/api/v2/highlights/{h.id}", headers=headers, json={"is_mastered": True},
    )
    assert r.status_code == 400


def test_patch_rejects_favoriting_discarded(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", is_discarded=True)
    resp = client.patch(
        f"/api/v2/highlights/{h.id}",
        headers=headers,
        json={"is_favorited": True},
    )
    assert resp.status_code == 400


# ── Highlight-level tags ─────────────────────────────────────────────────────


def test_list_tags_empty_when_none(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    resp = client.get(f"/api/v2/highlights/{h.id}/tags", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"tags": []}


def test_add_tag_creates_link_and_returns_list(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.post(
        f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "Python"},
    )
    assert r.status_code == 201
    # Tags are normalized to lowercase.
    assert r.json() == {"tags": ["python"]}


def test_add_tag_is_idempotent(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "ml"})
    r = client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "ml"})
    assert r.status_code == 201
    assert r.json() == {"tags": ["ml"]}


def test_add_tag_normalizes_whitespace_and_case(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.post(
        f"/api/v2/highlights/{h.id}/tags", headers=headers,
        json={"name": "  Deep   Learning  "},
    )
    assert r.status_code == 201
    assert r.json() == {"tags": ["deep learning"]}


def test_add_tag_rejects_reserved_names(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    for name in ("favorite", "Favorite", "FAVORITE", "discard"):
        r = client.post(
            f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": name},
        )
        assert r.status_code == 400, f"reserved name {name!r} should be rejected"


def test_add_tag_404_for_other_user(client, db, make_highlight):
    h = make_highlight(text="theirs")
    h.user_id = 2
    db.add(h); db.commit()
    headers = _auth_headers(db)
    r = client.post(
        f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "x"},
    )
    assert r.status_code == 404


def test_remove_tag_removes_link(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "a"})
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "b"})
    r = client.delete(f"/api/v2/highlights/{h.id}/tags/a", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"tags": ["b"]}


def test_remove_tag_idempotent(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.delete(f"/api/v2/highlights/{h.id}/tags/never-existed", headers=headers)
    assert r.status_code == 200
    assert r.json() == {"tags": []}


def test_get_highlight_includes_tags(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "z"})
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "a"})
    r = client.get(f"/api/v2/highlights/{h.id}", headers=headers)
    assert r.status_code == 200
    # Returned alphabetically for deterministic clients.
    assert r.json()["tags"] == ["a", "z"]


def test_search_filters_by_tag(client, db, make_highlight):
    headers = _auth_headers(db)
    h1 = make_highlight(text="alpha quote")
    h2 = make_highlight(text="alpha other")
    client.post(f"/api/v2/highlights/{h1.id}/tags", headers=headers, json={"name": "important"})
    # Search without tag filter: both match.
    r = client.get("/api/v2/highlights/search", headers=headers, params={"q": "alpha"})
    assert r.json()["count"] == 2
    # With tag filter: only the tagged one.
    r = client.get(
        "/api/v2/highlights/search", headers=headers,
        params={"q": "alpha", "tag": "important"},
    )
    assert r.json()["count"] == 1
    assert r.json()["results"][0]["id"] == h1.id


def test_search_results_include_tags(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="searchable")
    client.post(f"/api/v2/highlights/{h.id}/tags", headers=headers, json={"name": "topic"})
    r = client.get("/api/v2/highlights/search", headers=headers, params={"q": "searchable"})
    assert r.json()["results"][0]["tags"] == ["topic"]


# ── GET /api/v2/tags ─────────────────────────────────────────────────────────


def test_list_tag_summary_with_counts(client, db, make_highlight):
    headers = _auth_headers(db)
    h1 = make_highlight(text="x")
    h2 = make_highlight(text="y")
    client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "python"})
    client.post(f"/highlights/{h2.id}/tags/add", data={"new_tag": "python"})
    client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "ml"})
    resp = client.get("/api/v2/tags", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    by_name = {r["name"]: r for r in body["results"]}
    assert by_name["python"]["highlight_count"] == 2
    assert by_name["ml"]["highlight_count"] == 1
    # python sorted before ml (more uses).
    assert body["results"][0]["name"] == "python"


def test_list_tag_summary_excludes_reserved(client, db, make_highlight):
    """Legacy pseudo-tags 'favorite'/'discard' must never appear."""
    from app.models import Tag, HighlightTag
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    for name in ("favorite", "discard", "real-tag"):
        t = Tag(name=name)
        db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h.id, tag_id=t.id))
    db.commit()
    resp = client.get("/api/v2/tags", headers=headers)
    names = {r["name"] for r in resp.json()["results"]}
    assert "real-tag" in names
    assert "favorite" not in names
    assert "discard" not in names


def test_list_tag_summary_q_filter(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    for name in ("python", "django", "ml"):
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": name})
    resp = client.get("/api/v2/tags", headers=headers, params={"q": "py"})
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"python"}


def test_list_tag_summary_excludes_discarded_highlights(client, db, make_highlight):
    """A tag attached only to a discarded highlight should not be counted."""
    headers = _auth_headers(db)
    h = make_highlight(text="x", is_discarded=True)
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "ghost"})
    resp = client.get("/api/v2/tags", headers=headers)
    names = {r["name"] for r in resp.json()["results"]}
    assert "ghost" not in names


def test_list_tag_summary_requires_auth(client):
    assert client.get("/api/v2/tags").status_code == 401


# ── GET /api/v2/authors ──────────────────────────────────────────────────────


def test_authors_lists_distinct_with_counts(client, db, make_book, make_highlight):
    headers = _auth_headers(db)
    a1 = make_book(title="A1", author="Alice")
    a2 = make_book(title="A2", author="Alice")
    b = make_book(title="B1", author="Bob")
    make_highlight(text="x", book=a1)
    make_highlight(text="y", book=a1)
    make_highlight(text="z", book=a2)
    make_highlight(text="w", book=b)
    resp = client.get("/api/v2/authors", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    by_name = {r["name"]: r for r in body["results"]}
    assert by_name["Alice"]["book_count"] == 2
    assert by_name["Alice"]["highlight_count"] == 3
    assert by_name["Bob"]["book_count"] == 1
    assert by_name["Bob"]["highlight_count"] == 1
    # Sorted by highlight_count desc.
    assert body["results"][0]["name"] == "Alice"


def test_authors_q_filter(client, db, make_book, make_highlight):
    headers = _auth_headers(db)
    a = make_book(title="A", author="Alice")
    b = make_book(title="B", author="Bob")
    make_highlight(text="x", book=a)
    make_highlight(text="y", book=b)
    resp = client.get("/api/v2/authors", headers=headers, params={"q": "ali"})
    assert resp.status_code == 200
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Alice"}


def test_authors_excludes_discarded(client, db, make_book, make_highlight):
    headers = _auth_headers(db)
    a = make_book(title="A", author="Alice")
    make_highlight(text="x", book=a)
    make_highlight(text="y", book=a, is_discarded=True)
    resp = client.get("/api/v2/authors", headers=headers)
    body = resp.json()
    alice = next(r for r in body["results"] if r["name"] == "Alice")
    assert alice["highlight_count"] == 1


def test_authors_skips_null_author(client, db, make_book, make_highlight):
    headers = _auth_headers(db)
    a = make_book(title="A", author="Alice")
    nb = make_book(title="N", author=None)
    make_highlight(text="x", book=a)
    make_highlight(text="y", book=nb)
    resp = client.get("/api/v2/authors", headers=headers)
    names = {r["name"] for r in resp.json()["results"]}
    assert names == {"Alice"}


def test_authors_requires_auth(client):
    assert client.get("/api/v2/authors").status_code == 401


# ── GET /api/v2/stats ────────────────────────────────────────────────────────


def test_stats_returns_counts(client, db, make_highlight, make_book):
    headers = _auth_headers(db)
    book = make_book(title="B")
    make_highlight(text="a", book=book)
    make_highlight(text="b", book=book, is_favorited=True)
    make_highlight(text="c", book=book, is_discarded=True)
    make_highlight(text="d", book=book, is_mastered=True)
    resp = client.get("/api/v2/stats", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["highlights_total"] == 4
    assert body["highlights_active"] == 3      # excludes discarded only
    assert body["highlights_discarded"] == 1
    assert body["highlights_favorited"] == 1
    assert body["highlights_mastered"] == 1
    assert body["books_total"] == 1
    # Active + not mastered = 2 (a, b). c is discarded, d is mastered.
    assert body["review_due_today"] == 2
