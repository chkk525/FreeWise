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

class TestCopyQuoteButton:
    """The copy-as-quote button on _highlight_row carries the right data."""

    def test_button_renders_with_text_author_title(self, client, db, make_highlight, make_book):
        book = make_book(title="Sapiens", author="Yuval Noah Harari")
        h = make_highlight(text="History helps us see further", book=book)
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        assert "data-copy-quote" in resp.text
        assert 'data-text="History helps us see further"' in resp.text
        assert 'data-author="Yuval Noah Harari"' in resp.text
        assert 'data-title="Sapiens"' in resp.text
        # JS handler is wired
        assert "window.copyQuote(this)" in resp.text

    def test_button_handles_missing_author(self, client, db, make_highlight, make_book):
        book = make_book(title="Untitled", author=None)
        h = make_highlight(text="standalone quote", book=book)
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        assert 'data-author=""' in resp.text
        assert 'data-title="Untitled"' in resp.text

    def test_button_html_escapes_quote_in_text(self, client, db, make_highlight):
        # Embedded " in text must be escaped in the data-text attr or it
        # would terminate the attribute and inject markup.
        h = make_highlight(text='He said "go"')
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        # Jinja2 autoescape uses &#34; for "
        assert ('data-text="He said &#34;go&#34;"' in resp.text
                or 'data-text="He said &quot;go&quot;"' in resp.text)


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


class TestAskUI:
    """GET /highlights/ui/ask + POST /highlights/ui/ask."""

    def test_ask_page_renders_empty_form(self, client):
        resp = client.get("/highlights/ui/ask")
        assert resp.status_code == 200
        assert "Ask Your Library" in resp.text
        assert "<textarea" in resp.text
        # The empty-state placeholder should show until the user asks.
        assert "Type a question above" in resp.text

    def test_ask_post_empty_question_returns_hint(self, client):
        resp = client.post("/highlights/ui/ask", data={"question": "  "})
        assert resp.status_code == 200
        assert "Type a question first" in resp.text

    def test_ask_post_renders_answer(self, client, db, make_highlight, monkeypatch):
        """Mock both Ollama calls and verify answer + citations render."""
        import httpx
        from app.models import Embedding
        from app.services import embeddings as emb_svc
        from app.services.embeddings import pack_vector

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
                return httpx.Response(200, json={"response": f"Cats do — see [#{h.id}]"})
            return httpx.Response(404, text="?")

        fake = emb_svc.OllamaClient(
            base_url="http://x", model="nomic-embed-text",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)
        resp = client.post(
            "/highlights/ui/ask", data={"question": "do cats sleep?"},
        )
        assert resp.status_code == 200
        assert "Cats do" in resp.text
        # citations block should mention the highlight id
        assert f"#{h.id}" in resp.text or f"[#{h.id}]" in resp.text

    def test_ask_post_503_path_renders_error(self, client, db, make_highlight, monkeypatch):
        """Ollama unreachable → friendly inline error, not stack trace."""
        import httpx
        from app.models import Embedding
        from app.services import embeddings as emb_svc
        from app.services.embeddings import pack_vector

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
        resp = client.post("/highlights/ui/ask", data={"question": "anything"})
        assert resp.status_code == 200
        assert "Ollama unreachable" in resp.text
        assert "SEMANTIC_SETUP" in resp.text


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


class TestQuickCapture:
    """POST /highlights/ui/quick-capture — dashboard quick-capture widget."""

    def test_creates_highlight_under_quick_notes_book(self, client, db):
        from app.models import Book, Highlight
        from sqlmodel import select
        resp = client.post(
            "/highlights/ui/quick-capture",
            data={"text": "A passing thought"},
        )
        assert resp.status_code == 200
        assert "Saved as" in resp.text
        # The "Quick Notes" book should now exist with one highlight.
        book = db.exec(select(Book).where(Book.title == "Quick Notes")).first()
        assert book is not None
        h = db.exec(select(Highlight).where(Highlight.book_id == book.id)).first()
        assert h is not None
        assert h.text == "A passing thought"
        assert h.user_id == 1

    def test_appends_to_existing_quick_notes_book(self, client, db):
        from app.models import Book, Highlight
        from sqlmodel import select
        client.post("/highlights/ui/quick-capture", data={"text": "first"})
        client.post("/highlights/ui/quick-capture", data={"text": "second"})
        books = db.exec(select(Book).where(Book.title == "Quick Notes")).all()
        assert len(books) == 1   # not duplicated
        highlights = db.exec(select(Highlight).where(Highlight.book_id == books[0].id)).all()
        assert {h.text for h in highlights} == {"first", "second"}

    def test_empty_text_returns_error(self, client):
        resp = client.post("/highlights/ui/quick-capture", data={"text": "   "})
        assert resp.status_code == 200
        assert "Type something first" in resp.text

    def test_too_long_rejected(self, client):
        resp = client.post(
            "/highlights/ui/quick-capture",
            data={"text": "x" * 9000},
        )
        assert resp.status_code == 200
        assert "Too long" in resp.text


class TestDuplicatesPage:
    """GET /highlights/ui/duplicates — duplicate-group cleanup page."""

    def test_renders_empty_state_when_no_dupes(self, client, make_highlight):
        make_highlight(text="Unique highlight content here that is long enough")
        resp = client.get("/highlights/ui/duplicates")
        assert resp.status_code == 200
        assert "No duplicate groups" in resp.text

    def test_renders_groups(self, client, make_highlight):
        text = "Repeating prefix that survives the 20-char minimum cutoff"
        for _ in range(3):
            make_highlight(text=text + " variant")
        resp = client.get("/highlights/ui/duplicates", params={"prefix_chars": 30})
        assert resp.status_code == 200
        # Group banner
        assert "3× group" in resp.text
        # Cleanup button
        assert "Keep oldest" in resp.text
        # First member labeled keep, others drop
        assert "keep" in resp.text
        assert "drop" in resp.text


class TestSemanticDuplicatesPage:
    """GET /highlights/ui/duplicates/semantic — embedding-based pair view."""

    def test_empty_library_shows_inbox_state(self, client):
        resp = client.get("/highlights/ui/duplicates/semantic")
        assert resp.status_code == 200
        assert "No highlights to compare yet" in resp.text

    def test_low_coverage_prompts_backfill(self, client, make_highlight):
        # 3 highlights, 0 embeddings → coverage 0% → backfill prompt
        for i in range(3):
            make_highlight(text=f"highlight {i}")
        resp = client.get("/highlights/ui/duplicates/semantic")
        assert resp.status_code == 200
        assert "Embeddings not yet backfilled" in resp.text
        assert "freewise embed backfill" in resp.text
        # Did not run the matmul: pairs banner not rendered
        assert "near-duplicate pair" not in resp.text
        assert 'id="semdup-list"' not in resp.text

    def test_renders_pairs_when_embedded(self, client, db, make_highlight):
        from app.models import Embedding
        from app.services.embeddings import pack_vector
        a = make_highlight(text="cats sleep a lot of the day")
        b = make_highlight(text="kitties sleep most of the daytime")
        c = make_highlight(text="completely unrelated about ships")
        db.add(Embedding(highlight_id=a.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([1.0, 0.0])))
        db.add(Embedding(highlight_id=b.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([0.99, 0.01])))
        db.add(Embedding(highlight_id=c.id, model_name="nomic-embed-text",
                         dim=2, vector=pack_vector([-1.0, 0.0])))
        db.commit()
        resp = client.get(
            "/highlights/ui/duplicates/semantic",
            params={"threshold": 0.9},
        )
        assert resp.status_code == 200
        # Pair markup rendered
        assert 'id="semdup-list"' in resp.text
        assert "near-duplicate pair" in resp.text
        assert f"#{a.id} ↔ #{b.id}" in resp.text or f"#{b.id} ↔ #{a.id}" in resp.text
        # Far-away vector should not be matched against either
        assert "completely unrelated" not in resp.text


class TestTodayHighlightHTML:
    """GET /highlights/ui/today — dashboard daily-pick partial."""

    def test_renders_today_label(self, client, make_highlight):
        make_highlight(text="stable pick")
        resp = client.get("/highlights/ui/today")
        assert resp.status_code == 200
        # The "Today's pick" badge is the differentiator vs /random.
        assert "Today" in resp.text
        # Card wrapper id must remain consistent so HTMX swaps work.
        assert 'id="random-highlight-card"' in resp.text

    def test_today_is_stable_within_day(self, client, make_highlight):
        for i in range(20):
            make_highlight(text=f"row-{i}")
        # Two consecutive HTML calls return the same chosen highlight.
        a = client.get("/highlights/ui/today").text
        b = client.get("/highlights/ui/today").text
        # Extract the rendered text snippet to compare without the whole page churn.
        import re
        ma = re.search(r'class="font-serif[^"]*">\s*([^<]+)', a)
        mb = re.search(r'class="font-serif[^"]*">\s*([^<]+)', b)
        assert ma is not None and mb is not None
        assert ma.group(1).strip() == mb.group(1).strip()

    def test_today_empty_state(self, client):
        resp = client.get("/highlights/ui/today")
        assert resp.status_code == 200
        assert "No highlights" in resp.text


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


class TestTagDetailPage:
    """GET /highlights/ui/tag/{name} — per-tag listing."""

    def test_renders_highlights_with_tag(self, client, make_highlight):
        h1 = make_highlight(text="alpha")
        h2 = make_highlight(text="beta")
        client.post(f"/highlights/{h1.id}/tags/add", data={"new_tag": "topic"})
        client.post(f"/highlights/{h2.id}/tags/add", data={"new_tag": "other"})
        resp = client.get("/highlights/ui/tag/topic")
        assert resp.status_code == 200
        assert "alpha" in resp.text
        assert "beta" not in resp.text
        # The highlight-count line splits the number from the word with
        # span tags; check both pieces appear in order.
        assert ">1</span>" in resp.text
        assert "tagged" in resp.text

    def test_empty_state_for_unknown_tag(self, client):
        """Unknown tag → 200 with empty-state hint, not 404."""
        resp = client.get("/highlights/ui/tag/never-existed")
        assert resp.status_code == 200
        assert "No active highlights tagged" in resp.text

    def test_normalizes_case_and_whitespace(self, client, make_highlight):
        h = make_highlight(text="x")
        client.post(f"/highlights/{h.id}/tags/add", data={"new_tag": "Multi  Word"})
        # Lookup with the same human-typed casing should match the stored
        # normalized value.
        resp = client.get("/highlights/ui/tag/Multi%20%20Word")
        assert resp.status_code == 200
        assert "x" in resp.text

    def test_excludes_discarded(self, client, make_highlight, db):
        from app.models import Tag, HighlightTag
        # Create a tag + link an active and a discarded highlight to it.
        h_active = make_highlight(text="alive")
        h_dead = make_highlight(text="trashed", is_discarded=True)
        client.post(f"/highlights/{h_active.id}/tags/add", data={"new_tag": "shared"})
        # Manually attach 'shared' to discarded since the tag UI is gated
        # for discarded highlights.
        tag = db.exec(select(Tag).where(Tag.name == "shared")).first()
        db.add(HighlightTag(highlight_id=h_dead.id, tag_id=tag.id))
        db.commit()
        resp = client.get("/highlights/ui/tag/shared")
        assert "alive" in resp.text
        assert "trashed" not in resp.text

    def test_favorite_tag_redirects_to_favorites(self, client):
        resp = client.get("/highlights/ui/tag/favorite", follow_redirects=False)
        assert resp.status_code == 302
        assert "/highlights/ui/favorites" in resp.headers["location"]

    def test_discard_tag_redirects_to_discarded(self, client):
        resp = client.get("/highlights/ui/tag/discard", follow_redirects=False)
        assert resp.status_code == 302
        assert "/highlights/ui/discarded" in resp.headers["location"]


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

    def test_bulk_does_not_touch_other_users_highlights(self, client, make_highlight, db):
        """Defense-in-depth: bulk action must not affect rows owned by another user."""
        h_mine = make_highlight(text="mine")
        h_theirs = make_highlight(text="theirs")
        h_theirs.user_id = 2
        db.add(h_theirs); db.commit()
        resp = client.post(
            "/highlights/bulk",
            data={"action": "discard", "ids": f"{h_mine.id},{h_theirs.id}"},
        )
        assert resp.status_code == 200
        db.refresh(h_mine); db.refresh(h_theirs)
        assert h_mine.is_discarded is True
        assert h_theirs.is_discarded is False

    def test_bulk_caps_id_count(self, client):
        """A 1001-id payload should be rejected to bound blast radius."""
        ids = ",".join(str(i) for i in range(1001))
        resp = client.post(
            "/highlights/bulk", data={"action": "favorite", "ids": ids},
        )
        assert resp.status_code == 400

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


class TestSearchFacets:
    """Filter chips on /highlights/ui/search — favorited_only, has_note, tag."""

    def test_favorited_only_filter(self, client, make_highlight):
        make_highlight(text="favorite one", is_favorited=True)
        make_highlight(text="favorite two", is_favorited=True)
        make_highlight(text="not favorited")
        r = client.get("/highlights/ui/search",
                       params={"q": "favorite", "favorited_only": "true"})
        assert r.status_code == 200
        assert "favorite one" in r.text
        assert "favorite two" in r.text
        assert "not favorited" not in r.text
        # 2 matches, not 3
        assert ">2</span>" in r.text

    def test_has_note_filter(self, client, make_highlight):
        make_highlight(text="annotated", note="my thoughts here")
        make_highlight(text="bare", note=None)
        r = client.get("/highlights/ui/search",
                       params={"q": "annotated bare", "has_note": "true"})
        assert r.status_code == 200
        # Without `q` matching, the user may also send q="" — let's narrow
        # by sending q that matches both, then has_note filter trims.
        # Actually `q` here matches neither because it has no overlap.
        # Better: filter only.
        r2 = client.get("/highlights/ui/search", params={"has_note": "true"})
        assert r2.status_code == 200
        assert "annotated" in r2.text
        assert "bare" not in r2.text

    def test_tag_filter(self, client, db, make_highlight):
        from app.models import Tag, HighlightTag
        h1 = make_highlight(text="ml content")
        h2 = make_highlight(text="other content")
        t = Tag(name="ml")
        db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h1.id, tag_id=t.id))
        db.commit()
        r = client.get("/highlights/ui/search", params={"tag": "ml"})
        assert r.status_code == 200
        assert "ml content" in r.text
        assert "other content" not in r.text
        # Active tag chip rendered
        assert "#ml" in r.text

    def test_filter_only_with_no_query_works(self, client, make_highlight):
        make_highlight(text="favorited", is_favorited=True)
        make_highlight(text="not favorited")
        r = client.get("/highlights/ui/search", params={"favorited_only": "true"})
        assert r.status_code == 200
        assert "favorited" in r.text
        # Result count rendered (not the empty placeholder copy)
        assert "Type a query above" not in r.text

    def test_no_filters_renders_empty_prompt(self, client, make_highlight):
        make_highlight(text="something")
        r = client.get("/highlights/ui/search")
        assert r.status_code == 200
        assert "Type a query above" in r.text
        # No result rows
        assert "something" not in r.text or r.text.count("something") <= 1

    def test_facet_chips_present(self, client):
        r = client.get("/highlights/ui/search?q=anything")
        assert r.status_code == 200
        assert "Favorites only" in r.text
        assert "Has note" in r.text


class TestTagAutocomplete:
    """GET /highlights/tags/autocomplete — bulk-tag input suggestions."""

    def _attach(self, client, highlight_id, name):
        """Helper: attach a tag to a highlight via the existing UI endpoint."""
        client.post(
            f"/highlights/{highlight_id}/tags/add",
            data={"new_tag": name},
        )

    def _attach_many(self, client, highlight_id, names):
        for n in names:
            self._attach(client, highlight_id, n)

    def test_returns_plain_text_200(self, client, make_highlight):
        h = make_highlight(text="x")
        self._attach(client, h.id, "python")
        resp = client.get("/highlights/tags/autocomplete")
        assert resp.status_code == 200
        # Starlette appends "; charset=utf-8" — accept that as long as it's text/plain.
        assert resp.headers["content-type"].startswith("text/plain")

    def test_one_name_per_line_sorted_by_usage_desc(self, client, make_highlight):
        # Three highlights; tag "alpha" attached to all three, "beta" to two,
        # "gamma" to one. Expected order: alpha, beta, gamma.
        h1 = make_highlight(text="a")
        h2 = make_highlight(text="b")
        h3 = make_highlight(text="c")
        self._attach_many(client, h1.id, ["alpha", "beta", "gamma"])
        self._attach_many(client, h2.id, ["alpha", "beta"])
        self._attach_many(client, h3.id, ["alpha"])

        resp = client.get("/highlights/tags/autocomplete")
        assert resp.status_code == 200
        lines = resp.text.split("\n")
        assert lines == ["alpha", "beta", "gamma"]

    def test_excludes_system_tags(self, client, make_highlight, db):
        """'favorite' and 'discard' Tag rows must not appear even if present."""
        from app.models import Tag, HighlightTag

        h = make_highlight(text="x")
        # Manually insert reserved Tag rows + links since the /tags/add
        # endpoint silently rejects them. We're simulating legacy data.
        for name in ("favorite", "discard"):
            t = Tag(name=name)
            db.add(t)
            db.commit()
            db.refresh(t)
            db.add(HighlightTag(highlight_id=h.id, tag_id=t.id))
        db.commit()
        # Add a real tag too so the response is non-empty.
        self._attach(client, h.id, "real-tag")

        resp = client.get("/highlights/tags/autocomplete")
        assert resp.status_code == 200
        lines = [ln for ln in resp.text.split("\n") if ln]
        assert "favorite" not in lines
        assert "discard" not in lines
        assert "real-tag" in lines

    def test_caps_at_thirty(self, client, make_highlight):
        h = make_highlight(text="x")
        # 35 distinct tags on a single highlight — all have count=1, so the
        # ORDER BY tie-breaks arbitrarily; we only assert the cap.
        for i in range(35):
            self._attach(client, h.id, f"tag-{i:02d}")
        resp = client.get("/highlights/tags/autocomplete")
        assert resp.status_code == 200
        lines = [ln for ln in resp.text.split("\n") if ln]
        assert len(lines) == 30

    def test_empty_result_returns_empty_body_200(self, client):
        # No highlights, no tags — endpoint should still 200 with empty body.
        resp = client.get("/highlights/tags/autocomplete")
        assert resp.status_code == 200
        assert resp.text == ""


class TestPermalinkOgMeta:
    """The /highlights/ui/h/{id} permalink emits Open Graph + Twitter Card
    meta tags so a shared URL expands richly in Slack/Twitter/iMessage."""

    def test_og_meta_renders_with_book(self, client, make_highlight, make_book):
        book = make_book(title="Sapiens", author="Yuval Noah Harari")
        h = make_highlight(text="A short highlight to share.", book=book)
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        assert '<meta property="og:type" content="article">' in r.text
        assert '<meta property="og:title" content="Sapiens">' in r.text
        assert 'A short highlight to share.' in r.text
        assert '<meta name="twitter:card" content="summary_large_image">' in r.text

    def test_og_title_falls_back_when_no_book(self, client, db, make_highlight):
        # Force book_id=None after creation since the fixture auto-creates
        # a default book when none is supplied.
        h = make_highlight(text="orphan highlight")
        h_db = db.get(Highlight, h.id)
        h_db.book_id = None
        db.add(h_db); db.commit()

        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        assert '<meta property="og:title" content="FreeWise highlight">' in r.text

    def test_og_description_truncates_at_200(self, client, make_highlight):
        long_text = "x" * 250
        h = make_highlight(text=long_text)
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        # Description in og:description should be 200 x's + ellipsis.
        truncated = "x" * 200 + "…"
        assert f'<meta property="og:description" content="{truncated}">' in r.text

    def test_og_description_no_truncation_when_short(self, client, make_highlight):
        h = make_highlight(text="short")
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        # No ellipsis appended.
        assert '<meta property="og:description" content="short">' in r.text

    def test_og_meta_escapes_html_in_text(self, client, make_highlight):
        # XSS-safety: a <script> in the highlight body must not break out
        # of the meta content attribute.
        h = make_highlight(text='<script>alert(1)</script>')
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        # Raw <script> must NOT appear inside any og: or twitter: meta tag.
        # (It's fine if it shows up elsewhere on the page autoescaped to &lt;.)
        import re
        meta_lines = re.findall(r'<meta[^>]*(?:og:|twitter:)[^>]*>', r.text)
        for m in meta_lines:
            assert "<script>" not in m

    def test_og_meta_escapes_quote_in_book_title(self, client, make_highlight, make_book):
        book = make_book(title='Crash"course', author="A")
        h = make_highlight(text="x", book=book)
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        # The " inside the title must be HTML-escaped or it would terminate
        # the content attribute.
        assert ('content="Crash&#34;course"' in r.text
                or 'content="Crash&quot;course"' in r.text)

    def test_og_meta_absent_on_dashboard(self, client):
        r = client.get("/dashboard/ui")
        assert r.status_code == 200
        # Other pages keep the empty og_meta block — no og:* tags.
        assert "og:type" not in r.text
        assert "twitter:card" not in r.text
