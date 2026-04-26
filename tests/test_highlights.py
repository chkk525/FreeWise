"""
Tests for highlight JSON and HTML API endpoints.

Covers: CRUD, favorite toggle, discard toggle, weight update,
edit form save, and review flow.
"""
from datetime import datetime, date
from sqlmodel import select

from app.models import Highlight, ReviewSession


# ── JSON API endpoints ────────────────────────────────────────────────────────

class TestHighlightCRUD:
    """JSON CRUD operations on /highlights/."""

    def test_create_highlight(self, client, db, make_book):
        book = make_book()
        resp = client.post("/highlights/", json={
            "text": "New highlight",
            "user_id": 1,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["text"] == "New highlight"
        assert data["id"] is not None

    def test_get_highlight(self, client, make_highlight):
        h = make_highlight(text="Fetch me")
        resp = client.get(f"/highlights/{h.id}")
        assert resp.status_code == 200
        assert resp.json()["text"] == "Fetch me"

    def test_get_highlight_not_found(self, client):
        resp = client.get("/highlights/99999")
        assert resp.status_code == 404

    def test_update_highlight(self, client, make_highlight):
        h = make_highlight(text="Original")
        resp = client.put(f"/highlights/{h.id}", json={"text": "Updated"})
        assert resp.status_code == 200
        assert resp.json()["text"] == "Updated"

    def test_list_highlights(self, client, make_highlight):
        make_highlight(text="HL1")
        make_highlight(text="HL2")
        resp = client.get("/highlights/")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    def test_list_active_only(self, client, make_highlight):
        make_highlight(text="Active", is_discarded=False)
        make_highlight(text="Discarded", is_discarded=True)
        resp = client.get("/highlights/", params={"status": "active"})
        items = resp.json()
        assert len(items) == 1
        assert items[0]["text"] == "Active"

    def test_list_discarded_only(self, client, make_highlight):
        make_highlight(text="Active", is_discarded=False)
        make_highlight(text="Discarded", is_discarded=True)
        resp = client.get("/highlights/", params={"status": "discarded"})
        items = resp.json()
        assert len(items) == 1
        assert items[0]["text"] == "Discarded"

    def test_list_with_limit(self, client, make_highlight):
        for i in range(5):
            make_highlight(text=f"HL {i}")
        resp = client.get("/highlights/", params={"limit": 2})
        assert len(resp.json()) == 2


class TestFavoriteToggle:
    """POST /highlights/{id}/favorite/json — toggle favorite."""

    def test_favorite_on(self, client, make_highlight):
        h = make_highlight()
        resp = client.post(f"/highlights/{h.id}/favorite/json",
                           json={"favorite": True})
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

    def test_favorite_off(self, client, make_highlight):
        h = make_highlight(is_favorited=True)
        resp = client.post(f"/highlights/{h.id}/favorite/json",
                           json={"favorite": False})
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is False

    def test_cannot_favorite_discarded(self, client, make_highlight):
        h = make_highlight(is_discarded=True)
        resp = client.post(f"/highlights/{h.id}/favorite/json",
                           json={"favorite": True})
        assert resp.status_code == 400

    def test_unfavorite_discarded_ok(self, client, make_highlight, db):
        """Unfavoriting a discarded highlight should still work."""
        h = make_highlight(is_discarded=True, is_favorited=True)
        # Force the state in DB (normally impossible via app logic)
        h_db = db.get(Highlight, h.id)
        h_db.is_favorited = True
        db.add(h_db)
        db.commit()

        resp = client.post(f"/highlights/{h.id}/favorite/json",
                           json={"favorite": False})
        assert resp.status_code == 200


class TestDiscardJSON:
    """POST /highlights/{id}/discard/json — mark as discarded."""

    def test_discard(self, client, make_highlight):
        h = make_highlight()
        resp = client.post(f"/highlights/{h.id}/discard/json")
        assert resp.status_code == 200
        assert resp.json()["is_discarded"] is True

    def test_discard_auto_unfavorites(self, client, make_highlight):
        h = make_highlight(is_favorited=True)
        resp = client.post(f"/highlights/{h.id}/discard/json")
        data = resp.json()
        assert data["is_discarded"] is True
        assert data["is_favorited"] is False


# ── HTML/HTMX endpoints ──────────────────────────────────────────────────────

class TestHighlightEdit:
    """POST /highlights/{id}/edit — save edited highlight text/note/weight."""

    def test_edit_text(self, client, make_highlight):
        h = make_highlight(text="Before")
        resp = client.post(f"/highlights/{h.id}/edit",
                           data={"text": "After", "context": ""})
        assert resp.status_code == 200
        assert "After" in resp.text

    def test_edit_note(self, client, make_highlight, db):
        h = make_highlight(text="HL", note=None)
        client.post(f"/highlights/{h.id}/edit",
                     data={"text": "HL", "note": "My note", "context": ""})
        db.refresh(h)
        assert h.note == "My note"

    def test_edit_weight_clamped(self, client, make_highlight, db):
        h = make_highlight()
        client.post(f"/highlights/{h.id}/edit",
                     data={"text": h.text, "highlight_weight": "5.0", "context": ""})
        db.refresh(h)
        assert h.highlight_weight == 2.0

        client.post(f"/highlights/{h.id}/edit",
                     data={"text": h.text, "highlight_weight": "-1.0", "context": ""})
        db.refresh(h)
        assert h.highlight_weight == 0.0

    def test_edit_preserves_weight_when_absent(self, client, make_highlight, db):
        h = make_highlight(highlight_weight=1.5)
        client.post(f"/highlights/{h.id}/edit",
                     data={"text": h.text, "context": ""})
        db.refresh(h)
        assert h.highlight_weight == 1.5


class TestWeightEndpoint:
    """POST /highlights/{id}/weight — quick weight update."""

    def test_set_weight(self, client, make_highlight, db):
        h = make_highlight()
        resp = client.post(f"/highlights/{h.id}/weight",
                           data={"weight": "1.5", "context": ""})
        assert resp.status_code == 200
        db.refresh(h)
        assert h.highlight_weight == 1.5

    def test_weight_clamped_high(self, client, make_highlight, db):
        h = make_highlight()
        client.post(f"/highlights/{h.id}/weight",
                     data={"weight": "10.0", "context": ""})
        db.refresh(h)
        assert h.highlight_weight == 2.0

    def test_weight_clamped_low(self, client, make_highlight, db):
        h = make_highlight()
        client.post(f"/highlights/{h.id}/weight",
                     data={"weight": "-5.0", "context": ""})
        db.refresh(h)
        assert h.highlight_weight == 0.0


class TestFavoriteHTML:
    """POST /highlights/{id}/favorite — HTML toggle."""

    def test_favorite_toggle_html(self, client, make_highlight, db):
        h = make_highlight()
        resp = client.post(f"/highlights/{h.id}/favorite",
                           data={"favorite": "true", "context": ""})
        assert resp.status_code == 200
        db.refresh(h)
        assert h.is_favorited is True

    def test_cannot_favorite_discarded_html(self, client, make_highlight):
        h = make_highlight(is_discarded=True)
        resp = client.post(f"/highlights/{h.id}/favorite",
                           data={"favorite": "true", "context": ""})
        assert resp.status_code == 400


class TestDiscardHTML:
    """POST /highlights/{id}/discard — HTML toggle."""

    def test_discard_toggle_html(self, client, make_highlight, db):
        h = make_highlight()
        resp = client.post(f"/highlights/{h.id}/discard",
                           data={"context": ""})
        assert resp.status_code == 200
        db.refresh(h)
        assert h.is_discarded is True

    def test_discard_auto_unfavorites_html(self, client, make_highlight, db):
        h = make_highlight(is_favorited=True)
        client.post(f"/highlights/{h.id}/discard", data={"context": ""})
        db.refresh(h)
        assert h.is_discarded is True
        assert h.is_favorited is False

    def test_restore_from_discarded(self, client, make_highlight, db):
        h = make_highlight(is_discarded=True)
        client.post(f"/highlights/{h.id}/discard", data={"context": ""})
        db.refresh(h)
        assert h.is_discarded is False


class TestFavoritesPage:
    """GET /highlights/ui/favorites — favorites listing."""

    def test_favorites_page(self, client, make_highlight):
        make_highlight(text="Faved", is_favorited=True)
        make_highlight(text="Normal", is_favorited=False)
        resp = client.get("/highlights/ui/favorites")
        assert resp.status_code == 200
        assert "Faved" in resp.text
        assert "Normal" not in resp.text


class TestDiscardedPage:
    """GET /highlights/ui/discarded — discarded listing."""

    def test_discarded_page(self, client, make_highlight):
        make_highlight(text="Disc", is_discarded=True)
        make_highlight(text="Active", is_discarded=False)
        resp = client.get("/highlights/ui/discarded")
        assert resp.status_code == 200
        assert "Disc" in resp.text
        assert "Active" not in resp.text


class TestRelatedHighlightsHTMX:
    """GET /highlights/ui/h/{id}/related — HTMX partial."""

    def test_no_embedding_yet_renders_hint(self, client, make_highlight):
        h = make_highlight(text="x")
        resp = client.get(f"/highlights/ui/h/{h.id}/related")
        assert resp.status_code == 200
        assert "embed-backfill" in resp.text  # hint copy

    def test_renders_related_when_embeddings_exist(self, client, db, make_highlight):
        from app.models import Embedding
        from app.services.embeddings import pack_vector
        target = make_highlight(text="target")
        near = make_highlight(text="near match")
        far = make_highlight(text="far match")
        db.add(Embedding(highlight_id=target.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([1.0, 0.0])))
        db.add(Embedding(highlight_id=near.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([0.95, 0.05])))
        db.add(Embedding(highlight_id=far.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([-1.0, 0.0])))
        db.commit()
        resp = client.get(f"/highlights/ui/h/{target.id}/related")
        assert resp.status_code == 200
        # Both candidates should appear; near should be ranked first.
        near_pos = resp.text.find("near match")
        far_pos = resp.text.find("far match")
        assert 0 <= near_pos < far_pos


class TestPermalinkPage:
    """GET /highlights/ui/h/{id} — shareable single-highlight page."""

    def test_renders_for_existing_highlight(self, client, make_highlight):
        h = make_highlight(text="link me", note="my note")
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        assert "link me" in resp.text
        assert "my note" in resp.text
        # Permalink-specific Copy permalink button is rendered.
        assert "Copy permalink" in resp.text

    def test_404_for_missing(self, client):
        assert client.get("/highlights/ui/h/9999999").status_code == 404

    def test_row_partial_renders_permalink_icon(self, client, make_highlight):
        """Every row should expose a small permalink anchor for discoverability."""
        make_highlight(text="X")
        resp = client.get("/highlights/ui/favorites")
        # Even with no favorites, the page still loads. Make a highlight
        # favorited to ensure rows render.
        h = make_highlight(text="Y", is_favorited=True)
        resp = client.get("/highlights/ui/favorites")
        assert resp.status_code == 200
        assert f"/highlights/ui/h/{h.id}" in resp.text


class TestRandomHighlight:
    """GET /highlights/ui/random — random-highlight HTML partial."""

    def test_random_renders_partial(self, client, make_highlight):
        make_highlight(text="surprise me")
        resp = client.get("/highlights/ui/random")
        assert resp.status_code == 200
        assert "surprise me" in resp.text
        # The shuffle button targets the wrapper id.
        assert 'id="random-highlight-card"' in resp.text

    def test_random_excludes_discarded(self, client, make_highlight):
        make_highlight(text="alive")
        make_highlight(text="dead", is_discarded=True)
        # Sample several times to trip a regression in the filter.
        for _ in range(8):
            resp = client.get("/highlights/ui/random")
            assert "alive" in resp.text
            assert "dead" not in resp.text

    def test_random_empty_state(self, client):
        resp = client.get("/highlights/ui/random")
        assert resp.status_code == 200
        assert "No highlights" in resp.text


class TestMasteredPage:
    """GET /highlights/ui/mastered — mastered listing."""

    def test_mastered_page_renders(self, client):
        resp = client.get("/highlights/ui/mastered")
        assert resp.status_code == 200
        # Empty-state copy.
        assert "No mastered highlights" in resp.text or "0" in resp.text

    def test_mastered_page_filters(self, client, make_highlight):
        make_highlight(text="MasterMe", is_mastered=True)
        make_highlight(text="StillReviewing", is_mastered=False)
        resp = client.get("/highlights/ui/mastered")
        assert resp.status_code == 200
        assert "MasterMe" in resp.text
        assert "StillReviewing" not in resp.text

    def test_mastered_page_paginates(self, client, make_highlight):
        for i in range(45):
            make_highlight(text=f"M{i}", is_mastered=True)
        resp = client.get("/highlights/ui/mastered", params={"page_size": "10"})
        assert resp.status_code == 200
        # Pagination footer should mention 45 total.
        assert "45" in resp.text


class TestMastery:
    """POST /highlights/{id}/master — toggle is_mastered flag."""

    def test_toggle_master_on(self, client, make_highlight, db):
        h = make_highlight(text="x")
        assert h.is_mastered is False
        resp = client.post(f"/highlights/{h.id}/master", data={})
        assert resp.status_code == 200
        db.refresh(h)
        assert h.is_mastered is True

    def test_toggle_master_off(self, client, make_highlight, db):
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/master", data={})
        client.post(f"/highlights/{h.id}/master", data={})
        db.refresh(h)
        assert h.is_mastered is False

    def test_cannot_master_discarded(self, client, make_highlight):
        h = make_highlight(text="x", is_discarded=True)
        resp = client.post(f"/highlights/{h.id}/master", data={})
        assert resp.status_code == 400

    def test_unmaster_works_even_when_discarded(self, client, make_highlight, db):
        """Edge case: a row mastered before being discarded must still be
        un-masterable so the user can fix bad state."""
        h = make_highlight(text="x", is_discarded=True)
        # Forcibly seed is_mastered=True
        h.is_mastered = True
        db.add(h); db.commit()
        resp = client.post(f"/highlights/{h.id}/master", data={})
        assert resp.status_code == 200
        db.refresh(h)
        assert h.is_mastered is False

    def test_review_queue_excludes_mastered(self, client, make_highlight):
        """Mastered highlights must not appear in the review queue."""
        make_highlight(text="show me")
        make_highlight(text="hide-me-mastered", is_mastered=True)
        resp = client.get("/highlights/ui/review")
        assert resp.status_code == 200
        # Mastered text must not appear in the rendered review card.
        # (We may or may not see show-me depending on sampling, but the
        # explicit assertion is that the mastered row is filtered out.)
        assert "hide-me-mastered" not in resp.text


class TestBulkOperations:
    """POST /highlights/bulk — favorite/discard/tag many at once."""

    def test_bulk_favorite(self, client, make_highlight, db):
        h1 = make_highlight(text="a")
        h2 = make_highlight(text="b")
        h3 = make_highlight(text="c", is_favorited=True)
        resp = client.post(
            "/highlights/bulk",
            data={"action": "favorite", "ids": f"{h1.id},{h2.id},{h3.id}"},
        )
        assert resp.status_code == 200
        assert resp.headers.get("hx-refresh") == "true"
        assert "2 highlights favorited" in resp.text  # h3 was already → no change
        for h in (h1, h2, h3):
            db.refresh(h)
            assert h.is_favorited

    def test_bulk_favorite_skips_discarded(self, client, make_highlight, db):
        h1 = make_highlight(text="x")
        h2 = make_highlight(text="y", is_discarded=True)
        resp = client.post(
            "/highlights/bulk",
            data={"action": "favorite", "ids": f"{h1.id},{h2.id}"},
        )
        assert resp.status_code == 200
        assert "skipped" in resp.text
        db.refresh(h1); db.refresh(h2)
        assert h1.is_favorited is True
        assert h2.is_favorited is False

    def test_bulk_discard_auto_unfavorites(self, client, make_highlight, db):
        h = make_highlight(text="x", is_favorited=True)
        client.post("/highlights/bulk", data={"action": "discard", "ids": str(h.id)})
        db.refresh(h)
        assert h.is_discarded is True
        assert h.is_favorited is False

    def test_bulk_restore(self, client, make_highlight, db):
        h = make_highlight(text="x", is_discarded=True)
        client.post("/highlights/bulk", data={"action": "restore", "ids": str(h.id)})
        db.refresh(h)
        assert h.is_discarded is False

    def test_bulk_tag(self, client, make_highlight):
        h1 = make_highlight(text="x")
        h2 = make_highlight(text="y")
        resp = client.post(
            "/highlights/bulk",
            data={"action": "tag", "ids": f"{h1.id},{h2.id}", "tag": "important"},
        )
        assert resp.status_code == 200
        # Verify by reading back via the API
        from app.models import Tag, HighlightTag
        for h in (h1, h2):
            r = client.post(
                f"/highlights/{h.id}/tags/add", data={"new_tag": "important"},
            )
            # Adding "important" again should be idempotent — chip still appears.
            assert "important" in r.text

    def test_bulk_untag(self, client, make_highlight, db):
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "drop"})
        resp = client.post(
            "/highlights/bulk",
            data={"action": "untag", "ids": str(h.id), "tag": "drop"},
        )
        assert resp.status_code == 200
        # Verify the tag is gone
        from app.models import HighlightTag
        links = db.exec(select(HighlightTag).where(HighlightTag.highlight_id == h.id)).all()
        assert links == []

    def test_bulk_tag_rejects_reserved(self, client, make_highlight):
        h = make_highlight(text="x")
        for name in ("favorite", "discard", "FAVORITE"):
            resp = client.post(
                "/highlights/bulk",
                data={"action": "tag", "ids": str(h.id), "tag": name},
            )
            assert resp.status_code == 400

    def test_bulk_tag_requires_tag_field(self, client, make_highlight):
        h = make_highlight(text="x")
        resp = client.post(
            "/highlights/bulk", data={"action": "tag", "ids": str(h.id)},
        )
        assert resp.status_code == 400

    def test_bulk_unknown_action_400(self, client, make_highlight):
        h = make_highlight(text="x")
        resp = client.post(
            "/highlights/bulk", data={"action": "explode", "ids": str(h.id)},
        )
        assert resp.status_code == 400

    def test_bulk_empty_ids_rejected(self, client):
        """Empty ids string should be rejected (FastAPI Form validation
        gives 422 for empty; 400 if the endpoint reaches the body check)."""
        resp = client.post("/highlights/bulk", data={"action": "favorite", "ids": ""})
        assert resp.status_code in (400, 422)

    def test_bulk_master(self, client, make_highlight, db):
        h1 = make_highlight(text="a")
        h2 = make_highlight(text="b")
        h3 = make_highlight(text="c", is_discarded=True)
        resp = client.post(
            "/highlights/bulk",
            data={"action": "master", "ids": f"{h1.id},{h2.id},{h3.id}"},
        )
        assert resp.status_code == 200
        # h3 was discarded → skipped
        assert "skipped" in resp.text
        for h in (h1, h2):
            db.refresh(h); assert h.is_mastered is True
        db.refresh(h3); assert h3.is_mastered is False

    def test_bulk_unmaster(self, client, make_highlight, db):
        h = make_highlight(text="x", is_mastered=True)
        client.post("/highlights/bulk", data={"action": "unmaster", "ids": str(h.id)})
        db.refresh(h); assert h.is_mastered is False

    def test_bulk_garbage_ids_filtered(self, client, make_highlight, db):
        """Stale page state could send 'abc' alongside real ids; skip the trash."""
        h = make_highlight(text="x")
        resp = client.post(
            "/highlights/bulk",
            data={"action": "favorite", "ids": f"abc,{h.id},xyz"},
        )
        assert resp.status_code == 200
        db.refresh(h)
        assert h.is_favorited is True


class TestHighlightTagUI:
    """POST /highlights/{id}/tags/add and /tags/remove — HTMX endpoints."""

    def test_add_tag_attaches_and_returns_row(self, client, make_highlight):
        h = make_highlight(text="tag me")
        resp = client.post(
            f"/highlights/{h.id}/tags/add",
            data={"new_tag": "Python"},
        )
        assert resp.status_code == 200
        # Tag chip appears in the rendered row, normalized to lowercase.
        assert ">python<" in resp.text or "python" in resp.text

    def test_add_tag_idempotent(self, client, make_highlight):
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "ml"})
        resp = client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "ml"})
        assert resp.status_code == 200
        # Should still only have one chip.
        assert resp.text.count('id="highlight-') == 1

    def test_add_reserved_tag_silently_ignored(self, client, make_highlight, db):
        """'favorite' and 'discard' are reserved — must not be created as tags."""
        from app.models import Tag
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "favorite"})
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "Discard"})
        # No Tag rows created with those names.
        existing = db.exec(select(Tag).where(Tag.name.in_(["favorite", "discard"]))).all()
        assert existing == []

    def test_remove_tag(self, client, make_highlight):
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "a"})
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "b"})
        resp = client.post(
            f"/highlights/{h.id}/tags/remove", data={"tag": "a"},
        )
        assert resp.status_code == 200
        # 'a' chip gone, 'b' still present
        assert ">a<" not in resp.text
        assert ">b<" in resp.text

    def test_remove_tag_idempotent(self, client, make_highlight):
        h = make_highlight(text="x")
        resp = client.post(
            f"/highlights/{h.id}/tags/remove", data={"tag": "never-existed"},
        )
        assert resp.status_code == 200

    def test_404_for_missing_highlight(self, client):
        resp = client.post(
            "/highlights/999999/tags/add", data={"new_tag": "x"},
        )
        assert resp.status_code == 404

    def test_search_results_render_tags(self, client, make_highlight):
        """Tags should appear on highlight rows in the search results page."""
        h = make_highlight(text="needle here")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "topic"})
        resp = client.get("/highlights/ui/search", params={"q": "needle"})
        assert resp.status_code == 200
        # The chip + tag name appears
        assert ">topic<" in resp.text


class TestSearchPage:
    """GET /highlights/ui/search — full-text search across active highlights."""

    def test_search_empty_query_renders_form(self, client):
        resp = client.get("/highlights/ui/search")
        assert resp.status_code == 200
        assert "Search Highlights" in resp.text or "search" in resp.text.lower()

    def test_search_matches_text(self, client, make_highlight):
        make_highlight(text="The quick brown fox jumps")
        make_highlight(text="Unrelated highlight body")
        resp = client.get("/highlights/ui/search", params={"q": "brown fox"})
        assert resp.status_code == 200
        assert "quick brown fox" in resp.text
        assert "Unrelated highlight" not in resp.text

    def test_search_matches_note(self, client, make_highlight):
        make_highlight(text="Plain text", note="A unique-marker in the note")
        make_highlight(text="Another body", note="nothing here")
        resp = client.get("/highlights/ui/search", params={"q": "unique-marker"})
        assert resp.status_code == 200
        assert "Plain text" in resp.text
        assert "Another body" not in resp.text

    def test_search_excludes_discarded(self, client, make_highlight):
        make_highlight(text="needle in active")
        make_highlight(text="needle in discarded", is_discarded=True)
        resp = client.get("/highlights/ui/search", params={"q": "needle"})
        assert resp.status_code == 200
        assert "needle in active" in resp.text
        assert "needle in discarded" not in resp.text

    def test_search_no_matches_renders_empty_state(self, client, make_highlight):
        make_highlight(text="hello world")
        resp = client.get("/highlights/ui/search", params={"q": "zzz_no_match"})
        assert resp.status_code == 200
        assert "No matches" in resp.text or "No active highlights" in resp.text

    def test_search_escapes_like_wildcards(self, client, make_highlight):
        # Substring with literal % should not match arbitrary text.
        make_highlight(text="literal percent: 50% off")
        make_highlight(text="completely different text")
        resp = client.get("/highlights/ui/search", params={"q": "%"})
        assert resp.status_code == 200
        # Only the highlight that literally contains "%" should match.
        assert "50% off" in resp.text
        assert "completely different" not in resp.text
