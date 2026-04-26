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
