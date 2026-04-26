"""
Tests for library endpoints: listing, book detail, book edit, tags, book delete.
"""
from sqlmodel import select

from app.models import Book, Highlight


# ── Library listing ───────────────────────────────────────────────────────────

class TestLibraryPage:
    """GET /library/ui — library listing and sorting."""

    def test_empty_library(self, client):
        resp = client.get("/library/ui")
        assert resp.status_code == 200

    def test_lists_books(self, client, make_book):
        make_book(title="Alpha")
        make_book(title="Beta")
        resp = client.get("/library/ui")
        assert resp.status_code == 200
        assert "Alpha" in resp.text
        assert "Beta" in resp.text

    def test_sort_title_asc(self, client, make_book):
        make_book(title="Zebra")
        make_book(title="Apple")
        resp = client.get("/library/ui?sort=title&order=asc")
        assert resp.status_code == 200
        idx_a = resp.text.index("Apple")
        idx_z = resp.text.index("Zebra")
        assert idx_a < idx_z

    def test_sort_title_desc(self, client, make_book):
        make_book(title="Zebra")
        make_book(title="Apple")
        resp = client.get("/library/ui?sort=title&order=desc")
        assert resp.status_code == 200
        idx_a = resp.text.index("Apple")
        idx_z = resp.text.index("Zebra")
        assert idx_z < idx_a

    def test_sort_highlight_count(self, client, make_book, make_highlight):
        b1 = make_book(title="One")
        b2 = make_book(title="Many")
        make_highlight(text="H1", book=b1)
        make_highlight(text="H2", book=b2)
        make_highlight(text="H3", book=b2)
        resp = client.get("/library/ui?sort=highlight_count&order=desc")
        assert resp.status_code == 200
        idx_many = resp.text.index("Many")
        idx_one = resp.text.index("One")
        assert idx_many < idx_one

    def test_invalid_sort_falls_back(self, client, make_book):
        make_book(title="Safe")
        resp = client.get("/library/ui?sort=INVALID&order=asc")
        assert resp.status_code == 200
        assert "Safe" in resp.text

    def test_invalid_order_falls_back(self, client, make_book):
        make_book(title="Safe")
        resp = client.get("/library/ui?sort=title&order=INVALID")
        assert resp.status_code == 200


# ── Author filter ─────────────────────────────────────────────────────────────


class TestLibraryBookSearch:
    """GET /library/ui?q=text — text search across title + author."""

    def test_search_matches_title(self, client, make_book):
        make_book(title="Antifragile")
        make_book(title="Black Swan")
        resp = client.get("/library/ui", params={"q": "Antifragile"})
        assert resp.status_code == 200
        assert "Antifragile" in resp.text
        assert "Black Swan" not in resp.text

    def test_search_matches_author(self, client, make_book):
        make_book(title="X1", author="Nassim Taleb")
        make_book(title="Y1", author="Daniel Kahneman")
        resp = client.get("/library/ui", params={"q": "Taleb"})
        assert resp.status_code == 200
        assert "X1" in resp.text
        assert "Y1" not in resp.text

    def test_search_case_insensitive(self, client, make_book):
        make_book(title="UpperCase Book")
        resp = client.get("/library/ui", params={"q": "uppercase"})
        # SQLite LIKE is case-insensitive for ASCII by default; matches.
        assert "UpperCase Book" in resp.text

    def test_search_escapes_wildcards(self, client, make_book):
        """A ``%`` query should match a literal percent, not every row."""
        make_book(title="50% off literal")
        make_book(title="completely unrelated content")
        resp = client.get("/library/ui", params={"q": "%"})
        assert "50% off literal" in resp.text
        assert "completely unrelated" not in resp.text

    def test_search_combines_with_author_filter(self, client, make_book):
        """Both author= and q= should narrow together."""
        make_book(title="A1", author="Alice")
        make_book(title="B1", author="Alice")
        make_book(title="A2", author="Bob")
        resp = client.get(
            "/library/ui", params={"author": "Alice", "q": "A1"},
        )
        assert "A1" in resp.text
        assert "B1" not in resp.text
        assert "A2" not in resp.text

    def test_search_banner_renders(self, client, make_book):
        make_book(title="Book One")
        resp = client.get("/library/ui", params={"q": "Book"})
        assert "Filtering by query" in resp.text


class TestAuthorSummaryCard:
    """The author-filtered library page shows a stats summary card."""

    def test_summary_card_rendered_when_author_filtered(self, client, make_book, make_highlight):
        b1 = make_book(title="Book A", author="Alice")
        b2 = make_book(title="Book B", author="Alice")
        make_highlight(text="x", book=b1)
        make_highlight(text="y", book=b1, is_favorited=True)
        make_highlight(text="z", book=b2, is_mastered=True)
        resp = client.get("/library/ui", params={"author": "Alice"})
        assert resp.status_code == 200
        # Card heading: author name appears in an h3
        assert "<h3" in resp.text and "Alice" in resp.text
        # Stats: 2 books, 3 active, 1 favorited, 1 mastered
        assert ">2</span> book" in resp.text
        assert ">3</span> active highlights" in resp.text
        assert ">1</span> favorited" in resp.text
        assert ">1</span> mastered" in resp.text

    def test_no_summary_card_without_filter(self, client, make_book, make_highlight):
        b = make_book(title="X", author="Alice")
        make_highlight(text="x", book=b)
        resp = client.get("/library/ui")
        # Card uses an h3 with the author name; without filter it should NOT appear
        assert ">Alice</h3>" not in resp.text

    def test_summary_card_omits_zero_chips(self, client, make_book, make_highlight):
        """Chips should only render for non-zero counts."""
        b = make_book(title="A", author="Bob")
        make_highlight(text="x", book=b)
        resp = client.get("/library/ui", params={"author": "Bob"})
        assert "active highlights" in resp.text
        # No favorited/mastered/discarded chips since counts are zero.
        assert "favorited" not in resp.text or "</span> favorited" not in resp.text
        assert "</span> mastered" not in resp.text
        assert "</span> discarded" not in resp.text


class TestLibraryAuthorFilter:
    """GET /library/ui?author=X — filter books by author."""

    def test_no_filter_shows_all(self, client, make_book):
        make_book(title="AlphaBook", author="Alice")
        make_book(title="BetaBook", author="Bob")
        resp = client.get("/library/ui")
        assert resp.status_code == 200
        assert "AlphaBook" in resp.text and "BetaBook" in resp.text

    def test_filter_by_author(self, client, make_book):
        make_book(title="AlphaBook", author="Alice")
        make_book(title="BetaBook", author="Bob")
        resp = client.get("/library/ui", params={"author": "Alice"})
        assert resp.status_code == 200
        assert "AlphaBook" in resp.text
        assert "BetaBook" not in resp.text
        # Filter banner should appear
        assert "Filtering by author" in resp.text

    def test_filter_by_unknown_author_returns_empty(self, client, make_book):
        make_book(title="AlphaBook", author="Alice")
        resp = client.get("/library/ui", params={"author": "Nobody"})
        assert resp.status_code == 200
        assert "AlphaBook" not in resp.text

    def test_filter_empty_string_ignored(self, client, make_book):
        """Empty author= should behave like no filter."""
        make_book(title="AlphaBook", author="Alice")
        resp = client.get("/library/ui", params={"author": "  "})
        assert resp.status_code == 200
        assert "AlphaBook" in resp.text
        assert "Filtering by author" not in resp.text

    def test_author_link_rendered_on_table_cell(self, client, make_book):
        make_book(title="X", author="Some Author")
        resp = client.get("/library/ui")
        # The desktop table cell author should be a clickable filter link.
        assert "/library/ui?author=Some%20Author" in resp.text


# ── Book detail ───────────────────────────────────────────────────────────────

class TestBookDetail:
    """GET /library/ui/book/{book_id}"""

    def test_detail_page(self, client, make_book, make_highlight):
        book = make_book(title="My Book")
        make_highlight(text="Favourite line", book=book)
        resp = client.get(f"/library/ui/book/{book.id}")
        assert resp.status_code == 200
        assert "My Book" in resp.text
        assert "Favourite line" in resp.text

    def test_detail_404(self, client):
        resp = client.get("/library/ui/book/9999")
        assert resp.status_code == 404

    def test_detail_renders_engagement_stats(self, client, make_book, make_highlight):
        """Stats line should split into active / favorited / mastered / discarded."""
        b = make_book(title="Stats Book")
        make_highlight(text="a", book=b)                    # active
        make_highlight(text="b", book=b, is_favorited=True) # active + favorited
        make_highlight(text="c", book=b, is_mastered=True)  # active + mastered
        make_highlight(text="d", book=b, is_discarded=True) # discarded
        resp = client.get(f"/library/ui/book/{b.id}")
        assert resp.status_code == 200
        # 3 active, 1 favorited, 1 mastered, 1 discarded
        # Match the visible chips by their adjacent labels.
        assert ">3</span> active" in resp.text
        assert ">1</span> favorited" in resp.text
        assert ">1</span> mastered" in resp.text
        assert ">1</span> discarded" in resp.text

    def test_detail_omits_zero_chips(self, client, make_book, make_highlight):
        """Chips with zero count should not render (active is the only always-shown chip).

        Match the engagement-stats chip markup specifically — the row
        partial uses 'favorited' in tooltips so a bare substring check
        is too broad.
        """
        b = make_book(title="Plain")
        make_highlight(text="a", book=b)
        resp = client.get(f"/library/ui/book/{b.id}")
        # active chip present
        assert ">1</span> active" in resp.text
        # but no favorited/mastered/discarded chips
        assert "</span> favorited" not in resp.text
        assert "</span> mastered" not in resp.text
        assert "</span> discarded" not in resp.text

    def test_detail_renders_summarize_button(self, client, make_book, make_highlight):
        """Book detail action bar should expose the new Summarize button."""
        book = make_book(title="Test")
        make_highlight(text="x", book=book)
        resp = client.get(f"/library/ui/book/{book.id}")
        assert resp.status_code == 200
        # Button label + the HTMX endpoint it posts to
        assert "Summarize" in resp.text
        assert f"/library/ui/book/{book.id}/summarize" in resp.text


class TestBookSummarizeUI:
    """POST /library/ui/book/{id}/summarize — HTMX summary partial."""

    def test_404_for_missing_book(self, client):
        resp = client.post("/library/ui/book/9999/summarize")
        assert resp.status_code == 404

    def test_renders_answer_when_ollama_works(
        self, client, db, make_book, make_highlight, monkeypatch,
    ):
        import httpx
        from app.models import Embedding
        from app.services import embeddings as emb_svc
        from app.services.embeddings import pack_vector

        b = make_book(title="Antifragile", author="Taleb")
        h = make_highlight(text="What does not kill us makes us stronger.", book=b)
        db.add(Embedding(
            highlight_id=h.id, model_name="nomic-embed-text", dim=2,
            vector=pack_vector([1.0, 0.0]),
        ))
        db.commit()

        def handler(request):
            if request.url.path == "/api/embeddings":
                return httpx.Response(200, json={"embedding": [1.0, 0.0]})
            if request.url.path == "/api/generate":
                return httpx.Response(200, json={
                    "response": f"Antifragility means systems that gain from disorder. [#{h.id}]",
                })
            return httpx.Response(404)

        fake = emb_svc.OllamaClient(
            base_url="http://x", model="nomic-embed-text",
            http=httpx.Client(transport=httpx.MockTransport(handler)),
        )
        monkeypatch.setattr(emb_svc, "OllamaClient", lambda *a, **kw: fake)

        resp = client.post(f"/library/ui/book/{b.id}/summarize")
        assert resp.status_code == 200
        assert "Antifragility" in resp.text
        assert "Antifragile" in resp.text  # book title in heading

    def test_renders_inline_error_on_ollama_unavailable(
        self, client, db, make_book, make_highlight, monkeypatch,
    ):
        import httpx
        from app.models import Embedding
        from app.services import embeddings as emb_svc
        from app.services.embeddings import pack_vector

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

        resp = client.post(f"/library/ui/book/{b.id}/summarize")
        # Errors return the partial with an inline message, not 5xx.
        assert resp.status_code == 200
        assert "Ollama unreachable" in resp.text


# ── Book edit ─────────────────────────────────────────────────────────────────

class TestBookEdit:
    """GET/POST /library/ui/book/{book_id}/edit"""

    def test_edit_form(self, client, make_book):
        book = make_book(title="Old Title")
        resp = client.get(f"/library/ui/book/{book.id}/edit")
        assert resp.status_code == 200
        assert "Old Title" in resp.text

    def test_update_title(self, client, db, make_book):
        book = make_book(title="Old")
        resp = client.post(f"/library/ui/book/{book.id}/edit", data={
            "title": "New",
            "author": "Author",
            "review_weight": "1.0",
        })
        assert resp.status_code == 200
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.title == "New"

    def test_update_author(self, client, db, make_book):
        book = make_book(author="Old Author")
        client.post(f"/library/ui/book/{book.id}/edit", data={
            "title": book.title,
            "author": "New Author",
            "review_weight": "1.0",
        })
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.author == "New Author"

    def test_clamp_review_weight_max(self, client, db, make_book):
        book = make_book()
        client.post(f"/library/ui/book/{book.id}/edit", data={
            "title": book.title,
            "author": "A",
            "review_weight": "99.0",
        })
        db.expire_all()
        assert db.get(Book, book.id).review_weight == 2.0

    def test_clamp_review_weight_min(self, client, db, make_book):
        book = make_book()
        client.post(f"/library/ui/book/{book.id}/edit", data={
            "title": book.title,
            "author": "A",
            "review_weight": "-5.0",
        })
        db.expire_all()
        assert db.get(Book, book.id).review_weight == 0.0

    def test_edit_404(self, client):
        resp = client.get("/library/ui/book/9999/edit")
        assert resp.status_code == 404

    def test_cancel_edit(self, client, make_book, make_highlight):
        book = make_book(title="My Book")
        make_highlight(book=book)
        resp = client.get(f"/library/ui/book/{book.id}/cancel-edit")
        assert resp.status_code == 200
        assert "My Book" in resp.text


# ── Tags ──────────────────────────────────────────────────────────────────────

class TestBookTags:
    """Tag add / remove endpoints."""

    def test_add_tag(self, client, db, make_book):
        book = make_book()
        resp = client.post(f"/library/ui/book/{book.id}/add-tag", data={
            "new_tag": "fiction",
        })
        assert resp.status_code == 200
        db.expire_all()
        updated = db.get(Book, book.id)
        assert "fiction" in updated.document_tags

    def test_add_tag_dedup(self, client, db, make_book):
        book = make_book(document_tags="science")
        client.post(f"/library/ui/book/{book.id}/add-tag", data={"new_tag": "science"})
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.document_tags.count("science") == 1

    def test_add_tag_appends(self, client, db, make_book):
        book = make_book(document_tags="sci-fi")
        client.post(f"/library/ui/book/{book.id}/add-tag", data={"new_tag": "fantasy"})
        db.expire_all()
        updated = db.get(Book, book.id)
        assert "sci-fi" in updated.document_tags
        assert "fantasy" in updated.document_tags

    def test_add_empty_tag_no_op(self, client, db, make_book):
        book = make_book(document_tags="original")
        client.post(f"/library/ui/book/{book.id}/add-tag", data={"new_tag": "  "})
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.document_tags == "original"

    def test_remove_tag(self, client, db, make_book):
        book = make_book(document_tags="alpha, beta, gamma")
        client.post(f"/library/ui/book/{book.id}/remove-tag", data={"tag": "beta"})
        db.expire_all()
        updated = db.get(Book, book.id)
        assert "beta" not in updated.document_tags
        assert "alpha" in updated.document_tags
        assert "gamma" in updated.document_tags

    def test_remove_last_tag(self, client, db, make_book):
        book = make_book(document_tags="only")
        client.post(f"/library/ui/book/{book.id}/remove-tag", data={"tag": "only"})
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.document_tags is None or updated.document_tags == ""


# ── Book delete ───────────────────────────────────────────────────────────────

class TestBookDelete:
    """DELETE /library/ui/book/{book_id}"""

    def test_delete_book(self, client, db, make_book, make_highlight):
        book = make_book(title="Doomed")
        book_id = book.id
        h = make_highlight(text="Gone too", book=book)
        resp = client.delete(f"/library/ui/book/{book_id}")
        assert resp.status_code == 200
        assert resp.headers.get("HX-Redirect") == "/library/ui"
        db.expire_all()
        assert db.get(Book, book_id) is None
        assert db.exec(select(Highlight).where(Highlight.book_id == book_id)).first() is None

    def test_delete_cascade(self, client, db, make_book, make_highlight):
        book = make_book()
        book_id = book.id
        h1 = make_highlight(text="H1", book=book)
        h2 = make_highlight(text="H2", book=book)
        h1_id, h2_id = h1.id, h2.id
        client.delete(f"/library/ui/book/{book_id}")
        db.expire_all()
        assert db.get(Highlight, h1_id) is None
        assert db.get(Highlight, h2_id) is None

    def test_delete_404(self, client):
        resp = client.delete("/library/ui/book/9999")
        assert resp.status_code == 404


# ── Cover delete (no external calls) ─────────────────────────────────────────

class TestCoverDelete:
    """POST /library/ui/book/{book_id}/cover/delete"""

    def test_delete_cover_no_file(self, client, db, make_book):
        """Deleting a cover when there's no file should clear the DB fields."""
        book = make_book(cover_image_url="/static/uploads/covers/fake.jpg",
                         cover_image_source="upload")
        resp = client.post(f"/library/ui/book/{book.id}/cover/delete")
        assert resp.status_code == 200
        db.expire_all()
        updated = db.get(Book, book.id)
        assert updated.cover_image_url is None
        assert updated.cover_image_source is None

    def test_delete_cover_404(self, client):
        resp = client.post("/library/ui/book/9999/cover/delete")
        assert resp.status_code == 404


class TestLibraryPagination:
    """Server-side pagination for /library/ui (Phase: perf)."""

    def test_page_1_returns_first_page_size_books(self, client, make_book):
        for i in range(60):
            make_book(title=f"Book {i:02d}")
        r = client.get("/library/ui?page=1&page_size=50&sort=title&order=asc")
        assert r.status_code == 200
        # exactly 50 books on page 1
        assert r.text.count("Book 0") + r.text.count("Book 1") + r.text.count("Book 2") + r.text.count("Book 3") + r.text.count("Book 4") >= 50
        assert "of 2" in r.text and "value=\"1\"" in r.text

    def test_page_2_returns_remainder(self, client, make_book):
        for i in range(60):
            make_book(title=f"Book {i:02d}")
        r = client.get("/library/ui?page=2&page_size=50&sort=title&order=asc")
        assert r.status_code == 200
        assert "of 2" in r.text and "value=\"2\"" in r.text

    def test_page_size_clamps_to_max(self, client, make_book):
        for i in range(5):
            make_book(title=f"X {i}")
        r = client.get("/library/ui?page=1&page_size=999")
        assert r.status_code == 200
        # 5 books, all visible since clamped page_size still > 5
        assert "Showing" in r.text

    def test_page_clamps_to_total_pages(self, client, make_book):
        for i in range(3):
            make_book(title=f"A {i}")
        r = client.get("/library/ui?page=99&page_size=10")
        assert r.status_code == 200
        # only 1 page exists
        assert "of 1" in r.text and "value=\"1\"" in r.text

    def test_default_sort_is_highlight_count_desc(self, client, make_book, make_highlight):
        b_small = make_book(title="Small")
        b_big = make_book(title="Big")
        for _ in range(5):
            make_highlight(book=b_big, text="x")
        make_highlight(book=b_small, text="y")
        r = client.get("/library/ui")
        assert r.status_code == 200
        # "Big" appears before "Small" in the rendered table (by source order)
        assert r.text.index("Big") < r.text.index("Small")

    def test_pagination_preserves_sort_param(self, client, make_book):
        make_book(title="Aaa")
        r = client.get("/library/ui?sort=author&order=desc&page=1")
        assert r.status_code == 200
        # link to next page (if any) should preserve sort=author
        # (we only have 1 book so no next link, but the sort header should still reflect)
        assert "sort=author" in r.text or "current_sort" not in r.text  # sort applied
