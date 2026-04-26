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


# ── GET /api/v2/highlights/duplicates/semantic ───────────────────────────────


def test_semantic_duplicates_endpoint(client, db, make_highlight):
    from app.models import Embedding
    from app.services.embeddings import pack_vector
    headers = _auth_headers(db)
    h_a = make_highlight(text="alpha")
    h_b = make_highlight(text="beta")
    db.add(Embedding(highlight_id=h_a.id, model_name="nomic-embed-text",
                     dim=2, vector=pack_vector([1.0, 0.0])))
    db.add(Embedding(highlight_id=h_b.id, model_name="nomic-embed-text",
                     dim=2, vector=pack_vector([0.99, 0.14])))
    db.commit()
    resp = client.get(
        "/api/v2/highlights/duplicates/semantic", headers=headers,
        params={"threshold": 0.9},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    pair = body["results"][0]
    assert {pair["a_id"], pair["b_id"]} == {h_a.id, h_b.id}


def test_semantic_duplicates_empty_when_no_embeddings(client, db, make_highlight):
    headers = _auth_headers(db)
    make_highlight(text="x")
    resp = client.get("/api/v2/highlights/duplicates/semantic", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_semantic_duplicates_threshold_clamped(client, db):
    headers = _auth_headers(db)
    # threshold=2.0 should be 422 (le=1.0).
    resp = client.get(
        "/api/v2/highlights/duplicates/semantic", headers=headers,
        params={"threshold": 2.0},
    )
    assert resp.status_code == 422


def test_semantic_duplicates_requires_auth(client):
    assert client.get("/api/v2/highlights/duplicates/semantic").status_code == 401


# ── GET /api/v2/highlights/duplicates ────────────────────────────────────────


def test_duplicates_finds_matching_prefix(client, db, make_highlight):
    headers = _auth_headers(db)
    # Two highlights share a long identical prefix.
    text_a = "The quick brown fox jumps over the lazy dog and runs into the woods."
    make_highlight(text=text_a)
    make_highlight(text=text_a + " (re-imported variant)")
    # And one totally different highlight.
    make_highlight(text="Completely unrelated content here")

    resp = client.get(
        "/api/v2/highlights/duplicates", headers=headers,
        params={"prefix_chars": 50},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    grp = body["results"][0]
    assert grp["count"] == 2
    assert len(grp["members"]) == 2
    # Members ordered by id ascending so callers can keep the oldest.
    ids = [m["id"] for m in grp["members"]]
    assert ids == sorted(ids)


def test_duplicates_excludes_discarded(client, db, make_highlight):
    headers = _auth_headers(db)
    text = "Same prefix here for both"
    make_highlight(text=text)
    make_highlight(text=text + " variant", is_discarded=True)
    resp = client.get(
        "/api/v2/highlights/duplicates", headers=headers,
        params={"prefix_chars": 20, "min_group_size": 2},
    )
    # Only one non-discarded with this prefix → no group reported.
    assert resp.json()["count"] == 0


def test_duplicates_min_group_size_filter(client, db, make_highlight):
    headers = _auth_headers(db)
    # Two identical prefixes — group of 2 found with default min_group_size=2
    # but should be suppressed when min_group_size=3.
    text = "Repeating prefix that survives the 20-char minimum cutoff"
    for _ in range(2):
        make_highlight(text=text + " variant")
    body = client.get(
        "/api/v2/highlights/duplicates", headers=headers,
        params={"prefix_chars": 30, "min_group_size": 3},
    ).json()
    assert body["count"] == 0
    # Sanity: with min_group_size=2 the group does appear.
    body2 = client.get(
        "/api/v2/highlights/duplicates", headers=headers,
        params={"prefix_chars": 30, "min_group_size": 2},
    ).json()
    assert body2["count"] == 1


def test_duplicates_user_scoped(client, db, make_highlight):
    """Highlights from another user must not appear in the auth'd user's groups."""
    headers = _auth_headers(db)
    text = "Cross user prefix here"
    make_highlight(text=text + " a")
    h_other = make_highlight(text=text + " b")
    h_other.user_id = 2
    db.add(h_other); db.commit()
    body = client.get(
        "/api/v2/highlights/duplicates", headers=headers,
        params={"prefix_chars": 20, "min_group_size": 2},
    ).json()
    # Only one user-1 highlight with this prefix → no group.
    assert body["count"] == 0


def test_duplicates_requires_auth(client):
    assert client.get("/api/v2/highlights/duplicates").status_code == 401


def test_today_returns_stable_pick(client, db, make_highlight):
    """Two consecutive calls on the same day should return the same row."""
    headers = _auth_headers(db)
    for i in range(20):
        make_highlight(text=f"row-{i}")
    a = client.get("/api/v2/highlights/today", headers=headers).json()
    b = client.get("/api/v2/highlights/today", headers=headers).json()
    assert a["id"] == b["id"]


def test_today_salt_changes_pick(client, db, make_highlight):
    """Different salts should generally pick different rows.

    With 20 candidates the probability of two distinct salts colliding
    is 1/20 = 5%. We try several salt pairs to keep flakes near zero.
    """
    headers = _auth_headers(db)
    for i in range(20):
        make_highlight(text=f"row-{i}")
    seen = set()
    for salt in ("morning", "afternoon", "evening", "night", "early"):
        body = client.get(
            "/api/v2/highlights/today", headers=headers, params={"salt": salt},
        ).json()
        seen.add(body["id"])
    # At least 2 distinct picks across 5 salts on a 20-row corpus.
    assert len(seen) >= 2


def test_today_404_when_empty(client, db):
    headers = _auth_headers(db)
    resp = client.get("/api/v2/highlights/today", headers=headers)
    assert resp.status_code == 404


def test_today_excludes_discarded(client, db, make_highlight):
    """The daily pick must never select a discarded row."""
    headers = _auth_headers(db)
    make_highlight(text="alive")
    h = make_highlight(text="dead")
    h.is_discarded = True
    db.add(h); db.commit()
    body = client.get("/api/v2/highlights/today", headers=headers).json()
    assert body["text"] == "alive"


def test_today_requires_auth(client):
    assert client.get("/api/v2/highlights/today").status_code == 401


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


def test_append_note_to_existing(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x", note="original")
    r = client.post(
        f"/api/v2/highlights/{h.id}/note/append", headers=headers,
        json={"text": "follow-up"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["note"] == "original\n\nfollow-up"


def test_append_note_when_empty_initializes(client, db, make_highlight):
    """If note was empty, append should set it (no leading blank lines)."""
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.post(
        f"/api/v2/highlights/{h.id}/note/append", headers=headers,
        json={"text": "first thought"},
    )
    assert r.status_code == 200
    assert r.json()["note"] == "first thought"


def test_append_note_404_for_other_user(client, db, make_highlight):
    h = make_highlight(text="x")
    h.user_id = 2
    db.add(h); db.commit()
    headers = _auth_headers(db)
    r = client.post(
        f"/api/v2/highlights/{h.id}/note/append", headers=headers,
        json={"text": "x"},
    )
    assert r.status_code == 404


def test_append_note_rejects_combined_overflow(client, db, make_highlight):
    """U67 hardening: existing 8000 + append 8000 must NOT silently
    store a 16k-char note (SQLite has no hard cap)."""
    headers = _auth_headers(db)
    h = make_highlight(text="x", note="A" * 8000)
    r = client.post(
        f"/api/v2/highlights/{h.id}/note/append", headers=headers,
        json={"text": "B" * 5000},
    )
    assert r.status_code == 400
    assert "8191" in r.json()["detail"]


def test_append_note_rejects_empty(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    r = client.post(
        f"/api/v2/highlights/{h.id}/note/append", headers=headers,
        json={"text": ""},
    )
    # Pydantic min_length=1 rejects with 422; defensive 400 inside the
    # endpoint catches whitespace-only.
    assert r.status_code in (400, 422)


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


# ── GET /api/v2/highlights/{id}/suggest-tags ────────────────────────────────


def test_suggest_tags_uses_neighbor_tags(client, db, make_highlight):
    """Tags from semantic neighbors should bubble up as suggestions."""
    headers = _auth_headers(db)
    src = make_highlight(text="source about ml")
    near = make_highlight(text="another ml note")
    far = make_highlight(text="unrelated cooking")
    _seed_embedding(db, src.id, [1.0, 0.0])
    _seed_embedding(db, near.id, [0.95, 0.05])
    _seed_embedding(db, far.id, [-1.0, 0.0])
    # Tag the neighbor with what we expect to surface.
    client.post(f"/highlights/{near.id}/tags/add", data={"new_tag": "ml"})
    client.post(f"/highlights/{near.id}/tags/add", data={"new_tag": "ai"})
    # And the far row gets a different tag that should rank lower.
    client.post(f"/highlights/{far.id}/tags/add", data={"new_tag": "cooking"})

    resp = client.get(
        f"/api/v2/highlights/{src.id}/suggest-tags", headers=headers,
        params={"model": "test-model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    names = [r["name"] for r in body["results"]]
    # 'ml' and 'ai' should rank above 'cooking' (closer neighbor).
    assert "ml" in names
    assert "ai" in names
    if "cooking" in names:
        ml_idx = names.index("ml")
        cooking_idx = names.index("cooking")
        assert ml_idx < cooking_idx


def test_suggest_tags_skips_existing_tags(client, db, make_highlight):
    """Tags the source already has must not appear in suggestions."""
    headers = _auth_headers(db)
    src = make_highlight(text="x")
    near = make_highlight(text="y")
    _seed_embedding(db, src.id, [1.0, 0.0])
    _seed_embedding(db, near.id, [1.0, 0.0])
    client.post(f"/highlights/{src.id}/tags/add", data={"new_tag": "already"})
    client.post(f"/highlights/{near.id}/tags/add", data={"new_tag": "already"})
    client.post(f"/highlights/{near.id}/tags/add", data={"new_tag": "fresh"})
    resp = client.get(
        f"/api/v2/highlights/{src.id}/suggest-tags", headers=headers,
        params={"model": "test-model"},
    )
    names = [r["name"] for r in resp.json()["results"]]
    assert "fresh" in names
    assert "already" not in names


def test_suggest_tags_404_for_other_user(client, db, make_highlight):
    h = make_highlight(text="theirs")
    h.user_id = 2
    db.add(h); db.commit()
    headers = _auth_headers(db)
    resp = client.get(
        f"/api/v2/highlights/{h.id}/suggest-tags", headers=headers,
    )
    assert resp.status_code == 404


def test_suggest_tags_empty_when_source_unembedded(client, db, make_highlight):
    headers = _auth_headers(db)
    src = make_highlight(text="x")  # no embedding seeded
    resp = client.get(
        f"/api/v2/highlights/{src.id}/suggest-tags", headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


def test_suggest_tags_requires_auth(client, db, make_highlight):
    h = make_highlight(text="x")
    assert client.get(f"/api/v2/highlights/{h.id}/suggest-tags").status_code == 401


# ── GET /api/v2/highlights/{id}/related (semantic similarity) ────────────────


def _seed_embedding(db, highlight_id: int, vec: list[float], model: str = "test-model"):
    """Helper: write an Embedding row for the given highlight."""
    from app.models import Embedding
    from app.services.embeddings import pack_vector
    db.add(Embedding(
        highlight_id=highlight_id, model_name=model,
        dim=len(vec), vector=pack_vector(vec),
    ))
    db.commit()


def test_related_returns_top_k(client, db, make_highlight):
    headers = _auth_headers(db)
    target = make_highlight(text="target")
    near = make_highlight(text="near")
    far = make_highlight(text="far")
    _seed_embedding(db, target.id, [1.0, 0.0, 0.0])
    _seed_embedding(db, near.id, [0.9, 0.1, 0.0])
    _seed_embedding(db, far.id, [-1.0, 0.0, 0.0])
    resp = client.get(
        f"/api/v2/highlights/{target.id}/related",
        headers=headers, params={"model": "test-model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    # `near` should rank above `far`.
    assert body["results"][0]["id"] == near.id
    assert body["results"][1]["id"] == far.id
    # Each result should have a similarity score field.
    assert "similarity" in body["results"][0]


def test_related_excludes_self(client, db, make_highlight):
    """Source highlight must NOT appear in its own related list."""
    headers = _auth_headers(db)
    h = make_highlight(text="lonely")
    _seed_embedding(db, h.id, [1.0, 0.0])
    resp = client.get(
        f"/api/v2/highlights/{h.id}/related", headers=headers,
        params={"model": "test-model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert all(r["id"] != h.id for r in body["results"])


def test_related_returns_empty_when_no_target_embedding(client, db, make_highlight):
    """When the target highlight has no embedding for this model, count=0."""
    headers = _auth_headers(db)
    h = make_highlight(text="never embedded")
    resp = client.get(
        f"/api/v2/highlights/{h.id}/related", headers=headers,
        params={"model": "test-model"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 0
    assert body["results"] == []


def test_related_excludes_discarded_candidates(client, db, make_highlight):
    headers = _auth_headers(db)
    target = make_highlight(text="target")
    alive = make_highlight(text="alive")
    dead = make_highlight(text="dead", is_discarded=True)
    _seed_embedding(db, target.id, [1.0, 0.0])
    _seed_embedding(db, alive.id, [1.0, 0.0])
    _seed_embedding(db, dead.id, [1.0, 0.0])
    resp = client.get(
        f"/api/v2/highlights/{target.id}/related", headers=headers,
        params={"model": "test-model"},
    )
    body = resp.json()
    ids = [r["id"] for r in body["results"]]
    assert alive.id in ids
    assert dead.id not in ids


def test_related_404_for_other_user(client, db, make_highlight):
    h = make_highlight(text="theirs")
    h.user_id = 2
    db.add(h); db.commit()
    headers = _auth_headers(db)
    resp = client.get(f"/api/v2/highlights/{h.id}/related", headers=headers)
    assert resp.status_code == 404


def test_related_requires_auth(client):
    assert client.get("/api/v2/highlights/1/related").status_code == 401


# ── POST /api/v2/ask (RAG over highlights) ──────────────────────────────────


def test_ask_returns_answer_with_citations(client, db, make_highlight, monkeypatch):
    """End-to-end ask path with both Ollama embed + generate mocked."""
    import httpx, json as _json
    from app.services import embeddings as emb_svc
    from app.models import Embedding
    from app.services.embeddings import pack_vector

    headers = _auth_headers(db)
    h = make_highlight(text="cats sleep a lot")
    db.add(Embedding(
        highlight_id=h.id, model_name="nomic-embed-text", dim=2,
        vector=pack_vector([1.0, 0.0]),
    ))
    db.commit()

    def handler(request):
        if request.url.path == "/api/embeddings":
            return httpx.Response(200, json={"embedding": [1.0, 0.0]})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": f"Cats sleep, [#{h.id}]"})
        return httpx.Response(404, text="?")

    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)

    resp = client.post(
        "/api/v2/ask", headers=headers,
        json={"question": "do cats sleep?"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert "Cats sleep" in body["answer"]
    assert len(body["citations"]) == 1
    assert body["citations"][0]["id"] == h.id
    assert body["embed_model"] == "nomic-embed-text"


def test_ask_400_on_empty_question(client, db):
    headers = _auth_headers(db)
    for q in ("", "   "):
        r = client.post("/api/v2/ask", headers=headers, json={"question": q})
        assert r.status_code == 400


def test_ask_503_when_ollama_unreachable(client, db, make_highlight, monkeypatch):
    """If the embed call raises OllamaUnavailable the route should return 503,
    not 500 — so the CLI/MCP can show a setup hint instead of a stack trace."""
    import httpx
    from app.services import embeddings as emb_svc
    from app.models import Embedding
    from app.services.embeddings import pack_vector

    headers = _auth_headers(db)
    h = make_highlight(text="x")
    db.add(Embedding(
        highlight_id=h.id, model_name="nomic-embed-text", dim=1,
        vector=pack_vector([1.0]),
    ))
    db.commit()

    def handler(request):
        raise httpx.ConnectError("refused")

    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)

    resp = client.post(
        "/api/v2/ask", headers=headers, json={"question": "anything"},
    )
    assert resp.status_code == 503
    assert "Ollama" in resp.json()["detail"]


def test_ask_returns_hint_when_no_embeddings(client, db, monkeypatch):
    """If embeddings table is empty for the current model, return the
    helpful hint (200, not error)."""
    import httpx
    from app.services import embeddings as emb_svc

    headers = _auth_headers(db)

    def handler(request):
        return httpx.Response(200, json={"embedding": [1.0]})

    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)
    resp = client.post("/api/v2/ask", headers=headers, json={"question": "q"})
    assert resp.status_code == 200
    assert "embed-backfill" in resp.json()["answer"]


def test_ask_requires_auth(client):
    assert client.post("/api/v2/ask", json={"question": "q"}).status_code == 401


# ── POST /api/v2/books/{id}/summarize ───────────────────────────────────────


def test_summarize_book_uses_book_scope(client, db, make_highlight, make_book, monkeypatch):
    """summarize-book should only retrieve from the requested book's highlights."""
    import httpx
    from app.models import Embedding
    from app.services import embeddings as emb_svc
    from app.services.embeddings import pack_vector

    headers = _auth_headers(db)
    book_a = make_book(title="Target Book", author="A")
    book_b = make_book(title="Other Book", author="B")
    h_a = make_highlight(text="from target", book=book_a)
    h_b = make_highlight(text="from other", book=book_b)
    for h in (h_a, h_b):
        db.add(Embedding(
            highlight_id=h.id, model_name="nomic-embed-text", dim=2,
            vector=pack_vector([1.0, 0.0]),
        ))
    db.commit()

    def handler(request):
        if request.url.path == "/api/embeddings":
            return httpx.Response(200, json={"embedding": [1.0, 0.0]})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "summary text"})
        return httpx.Response(404)

    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)
    resp = client.post(f"/api/v2/books/{book_a.id}/summarize", headers=headers, json={})
    assert resp.status_code == 200
    body = resp.json()
    # Citations must be ONLY from book A.
    assert body["book_id"] == book_a.id
    assert body["book_title"] == "Target Book"
    cited_ids = {c["id"] for c in body["citations"]}
    assert h_a.id in cited_ids
    assert h_b.id not in cited_ids


def test_summarize_book_404_when_missing(client, db):
    headers = _auth_headers(db)
    resp = client.post("/api/v2/books/9999/summarize", headers=headers, json={})
    assert resp.status_code == 404


def test_summarize_book_404_for_other_users_book(client, db, make_book, make_highlight):
    """A book whose only highlights belong to user 2 must NOT be
    summarizable by a user-1 token, even if its book_id is guessed."""
    headers = _auth_headers(db)  # token for user 1
    b = make_book(title="Theirs")
    h = make_highlight(text="theirs", book=b)
    h.user_id = 2
    db.add(h); db.commit()
    resp = client.post(f"/api/v2/books/{b.id}/summarize", headers=headers, json={})
    assert resp.status_code == 404


def test_ask_top_k_clamped_at_50(client, db, make_highlight):
    """top_k=99999 should be rejected (422) — protects matmul + prompt."""
    headers = _auth_headers(db)
    make_highlight(text="x")
    resp = client.post(
        "/api/v2/ask", headers=headers,
        json={"question": "anything", "top_k": 99999},
    )
    assert resp.status_code == 422


def test_backfill_batch_size_clamped(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/embeddings/backfill", headers=headers,
        json={"batch_size": 99999},
    )
    assert resp.status_code == 422


def test_summarize_book_503_when_ollama_down(client, db, make_book, make_highlight, monkeypatch):
    import httpx
    from app.models import Embedding
    from app.services import embeddings as emb_svc
    from app.services.embeddings import pack_vector

    headers = _auth_headers(db)
    b = make_book(title="X")
    h = make_highlight(text="x", book=b)
    db.add(Embedding(
        highlight_id=h.id, model_name="nomic-embed-text", dim=1,
        vector=pack_vector([1.0]),
    ))
    db.commit()

    def handler(request):
        raise httpx.ConnectError("refused")
    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)
    resp = client.post(f"/api/v2/books/{b.id}/summarize", headers=headers, json={})
    assert resp.status_code == 503


def test_summarize_book_custom_question(client, db, make_book, make_highlight, monkeypatch):
    """Passing a custom question should override the default summarize prompt."""
    import httpx, json as _json
    from app.models import Embedding
    from app.services import embeddings as emb_svc
    from app.services.embeddings import pack_vector

    headers = _auth_headers(db)
    b = make_book(title="X")
    h = make_highlight(text="answer-y content", book=b)
    db.add(Embedding(
        highlight_id=h.id, model_name="nomic-embed-text", dim=1,
        vector=pack_vector([1.0]),
    ))
    db.commit()

    seen_prompts: list[str] = []

    def handler(request):
        if request.url.path == "/api/embeddings":
            seen_prompts.append(_json.loads(request.content)["prompt"])
            return httpx.Response(200, json={"embedding": [1.0]})
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "ok"})
        return httpx.Response(404)
    fake = emb_svc.OllamaClient(
        base_url="http://x", model="nomic-embed-text",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)
    custom = "What does this book say about productivity?"
    resp = client.post(
        f"/api/v2/books/{b.id}/summarize", headers=headers,
        json={"question": custom},
    )
    assert resp.status_code == 200
    # The embed call should have been the custom question, not the default summary prompt.
    assert any(custom in p for p in seen_prompts)


# ── POST /api/v2/embeddings/backfill (CLI driver endpoint) ───────────────────


def test_backfill_endpoint_returns_report(client, db, make_highlight, monkeypatch):
    """The endpoint should call the backfill service and return its report."""
    headers = _auth_headers(db)
    make_highlight(text="hi")

    # Patch the OllamaClient to a deterministic fake.
    import httpx, json as _json
    from app.services import embeddings as emb_svc

    def handler(request):
        body = _json.loads(request.content)
        return httpx.Response(200, json={"embedding": [float(len(body["prompt"]))]})

    fake_client = emb_svc.OllamaClient(
        base_url="http://x", model="test-model",
        http=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    real_client_cls = emb_svc.OllamaClient
    monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake_client)
    try:
        resp = client.post(
            "/api/v2/embeddings/backfill",
            headers=headers, json={"batch_size": 10, "model": "test-model"},
        )
    finally:
        monkeypatch.setattr(emb_svc, "OllamaClient", real_client_cls)
    assert resp.status_code == 200
    body = resp.json()
    assert body["embedded"] == 1
    assert body["remaining"] == 0
    assert body["model"] == "test-model"


# ── GET /api/v2/tags ─────────────────────────────────────────────────────────


# ── Tag rename / merge ──────────────────────────────────────────────────────


def test_tag_rename_renames_globally(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "python"})
    resp = client.post("/api/v2/tags/python/rename", headers=headers,
                       json={"new_name": "Python 3"})
    assert resp.status_code == 200
    body = resp.json()
    # Names normalize lowercase + collapsed whitespace.
    assert body["name"] == "python 3"
    # Verify the tag-list endpoint reflects the rename.
    listed = client.get(f"/api/v2/highlights/{h.id}/tags", headers=headers).json()
    assert listed["tags"] == ["python 3"]


def test_tag_rename_404_when_missing(client, db):
    headers = _auth_headers(db)
    resp = client.post("/api/v2/tags/never-existed/rename", headers=headers,
                       json={"new_name": "x"})
    assert resp.status_code == 404


def test_tag_rename_409_on_collision(client, db, make_highlight):
    """Renaming to an already-existing tag must 409 — caller should /merge."""
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "a"})
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "b"})
    resp = client.post("/api/v2/tags/a/rename", headers=headers,
                       json={"new_name": "b"})
    assert resp.status_code == 409


def test_tag_rename_rejects_reserved(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "x"})
    for name in ("favorite", "discard", "Favorite"):
        r = client.post("/api/v2/tags/x/rename", headers=headers,
                        json={"new_name": name})
        assert r.status_code == 400


def test_tag_merge_combines_links(client, db, make_highlight):
    headers = _auth_headers(db)
    h1 = make_highlight(text="A")
    h2 = make_highlight(text="B")
    h3 = make_highlight(text="C")
    # h1 has only "ml"; h2 has both; h3 has only "machine learning"
    client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "ml"})
    client.post(f"/highlights/{h2.id}/tags/add", data={"new_tag": "ml"})
    client.post(f"/highlights/{h2.id}/tags/add", data={"new_tag": "machine learning"})
    client.post(f"/highlights/{h3.id}/tags/add", data={"new_tag": "machine learning"})
    resp = client.post("/api/v2/tags/ml/merge", headers=headers,
                       json={"into": "machine learning"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "machine learning"
    # All 3 highlights should now carry the destination tag.
    for h in (h1, h2, h3):
        listed = client.get(f"/api/v2/highlights/{h.id}/tags", headers=headers).json()
        assert "machine learning" in listed["tags"]
        assert "ml" not in listed["tags"]
    # Source tag must be gone.
    summary = client.get("/api/v2/tags", headers=headers).json()
    assert "ml" not in {r["name"] for r in summary["results"]}


def test_tag_merge_404_when_missing(client, db):
    headers = _auth_headers(db)
    resp = client.post("/api/v2/tags/nope/merge", headers=headers,
                       json={"into": "alsonope"})
    assert resp.status_code == 404


def test_tag_merge_400_self(client, db, make_highlight):
    headers = _auth_headers(db)
    h = make_highlight(text="x")
    client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "x"})
    resp = client.post("/api/v2/tags/x/merge", headers=headers,
                       json={"into": "x"})
    assert resp.status_code == 400


# ── Author rename ───────────────────────────────────────────────────────────


def test_author_rename_updates_all_books(client, db, make_book, make_highlight):
    headers = _auth_headers(db)
    b1 = make_book(title="A", author="Old Name")
    b2 = make_book(title="B", author="Old Name")
    make_highlight(text="x", book=b1)
    make_highlight(text="y", book=b2)
    resp = client.post(
        "/api/v2/authors/rename", headers=headers,
        params={"name": "Old Name"}, json={"new_name": "New Name"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["book_count"] == 2
    db.refresh(b1); db.refresh(b2)
    assert b1.author == "New Name"
    assert b2.author == "New Name"


def test_author_rename_404_when_no_match(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/authors/rename", headers=headers,
        params={"name": "Nobody"}, json={"new_name": "X"},
    )
    assert resp.status_code == 404


def test_author_rename_400_empty_names(client, db, make_book):
    headers = _auth_headers(db)
    make_book(title="A", author="Real")
    for name, new_name in (("Real", "  "), ("  ", "x")):
        r = client.post(
            "/api/v2/authors/rename", headers=headers,
            params={"name": name}, json={"new_name": new_name},
        )
        assert r.status_code in (400, 404, 422)


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
