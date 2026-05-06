"""Integration tests for /api/v2/highlights/."""

from __future__ import annotations

from sqlmodel import select

from app.models import ApiToken, Book, Highlight


def _auth_headers(db, value: str = "tk") -> dict[str, str]:
    db.add(ApiToken(token_prefix=value[:16], token_hash=__import__("hashlib").sha256(value.encode()).hexdigest(), name="ext", user_id=1))
    db.commit()
    return {"Authorization": f"Token {value}"}


# ── POST /api/v2/highlights/ ──────────────────────────────────────────────────

def test_post_creates_highlight_and_book(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/highlights/",
        headers=headers,
        json={
            "highlights": [
                {"text": "Hello world", "title": "My Article", "author": "Jane"}
            ]
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body == {"created": 1, "skipped_duplicates": 0, "errors": []}

    books = db.exec(select(Book)).all()
    assert len(books) == 1
    assert books[0].title == "My Article"

    highlights = db.exec(select(Highlight)).all()
    assert len(highlights) == 1
    assert highlights[0].text == "Hello world"
    assert highlights[0].book_id == books[0].id
    assert highlights[0].user_id == 1


def test_post_dedupes_existing_highlight(client, db):
    headers = _auth_headers(db)
    payload = {
        "highlights": [
            {"text": "Same quote", "title": "B", "author": "A", "location": 5},
            {"text": "Same quote", "title": "B", "author": "A", "location": 5},
        ]
    }
    resp = client.post("/api/v2/highlights/", headers=headers, json=payload)
    assert resp.status_code == 201
    assert resp.json() == {"created": 1, "skipped_duplicates": 1, "errors": []}

    rows = db.exec(select(Highlight)).all()
    assert len(rows) == 1


def test_post_with_empty_list(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/highlights/", headers=headers, json={"highlights": []}
    )
    assert resp.status_code == 201
    assert resp.json() == {"created": 0, "skipped_duplicates": 0, "errors": []}
    assert db.exec(select(Highlight)).all() == []


def test_post_without_auth_returns_401(client):
    resp = client.post(
        "/api/v2/highlights/",
        json={"highlights": [{"text": "x"}]},
    )
    assert resp.status_code == 401


def test_post_persists_optional_fields(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/highlights/",
        headers=headers,
        json={
            "highlights": [
                {
                    "text": "Quote",
                    "title": "Article",
                    "author": "Author",
                    "note": "ny note",
                    "location": 7,
                    "location_type": "page",
                    "source_url": "https://example.com/x",
                    "source_type": "web",
                    "category": "articles",
                    "image_url": "https://example.com/cover.jpg",
                    "highlighted_at": "2026-04-19T01:02:03Z",
                }
            ]
        },
    )
    assert resp.status_code == 201
    assert resp.json()["created"] == 1

    h = db.exec(select(Highlight)).first()
    assert h.note == "ny note"
    assert h.location == 7
    assert h.location_type == "page"

    book = db.exec(select(Book)).first()
    assert book.cover_image_url == "https://example.com/cover.jpg"
    assert book.cover_image_source == "readwise_api"
    assert "url:https://example.com/x" in (book.document_tags or "")
    assert "source:web" in (book.document_tags or "")


def test_post_validates_text_required(client, db):
    headers = _auth_headers(db)
    resp = client.post(
        "/api/v2/highlights/",
        headers=headers,
        json={"highlights": [{"title": "no text"}]},
    )
    assert resp.status_code == 422


# ── GET /api/v2/highlights/ ───────────────────────────────────────────────────

def test_list_highlights_empty(client, db):
    headers = _auth_headers(db)
    resp = client.get("/api/v2/highlights/", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body == {"count": 0, "next": None, "previous": None, "results": []}


def test_list_highlights_pagination(client, db):
    headers = _auth_headers(db)
    # Create 60 highlights via the POST endpoint
    payload = {
        "highlights": [
            {"text": f"Quote {i}", "title": "B", "author": "A", "location": i}
            for i in range(60)
        ]
    }
    resp = client.post("/api/v2/highlights/", headers=headers, json=payload)
    assert resp.status_code == 201
    assert resp.json()["created"] == 60

    # Page 1 (default page_size=50)
    resp = client.get("/api/v2/highlights/", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 60
    assert len(body["results"]) == 50
    assert body["next"] is not None
    assert "page=2" in body["next"]
    assert body["previous"] is None

    # Page 2
    resp = client.get(
        "/api/v2/highlights/?page=2&page_size=50", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 10
    assert body["next"] is None
    assert body["previous"] is not None


def test_list_highlights_filter_by_book(client, db):
    headers = _auth_headers(db)
    client.post(
        "/api/v2/highlights/",
        headers=headers,
        json={
            "highlights": [
                {"text": "h1", "title": "A", "author": "x"},
                {"text": "h2", "title": "B", "author": "y"},
            ]
        },
    )
    book_a = db.exec(select(Book).where(Book.title == "A")).first()
    resp = client.get(
        f"/api/v2/highlights/?book_id={book_a.id}", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["text"] == "h1"
    assert body["results"][0]["title"] == "A"


def _seed_three_states(db, make_highlight):
    """Helper: one favorited, one discarded, one mastered, one plain."""
    plain = make_highlight(text="plain row")
    fav = make_highlight(text="fav row", is_favorited=True)
    disc = make_highlight(text="disc row", is_discarded=True)
    mas = make_highlight(text="mas row")
    mas.is_mastered = True
    db.add(mas)
    db.commit()
    db.refresh(mas)
    return {"plain": plain, "fav": fav, "disc": disc, "mas": mas}


def test_list_highlights_favorited_only(client, db, make_highlight):
    headers = _auth_headers(db)
    rows = _seed_three_states(db, make_highlight)
    resp = client.get("/api/v2/highlights/?favorited=true", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == rows["fav"].id
    assert body["results"][0]["is_favorited"] is True


def test_list_highlights_favorited_false_excludes_favorites(client, db, make_highlight):
    headers = _auth_headers(db)
    rows = _seed_three_states(db, make_highlight)
    resp = client.get("/api/v2/highlights/?favorited=false", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    ids = {r["id"] for r in body["results"]}
    assert rows["fav"].id not in ids
    # plain + disc + mas all excluded from favorites set
    assert {rows["plain"].id, rows["disc"].id, rows["mas"].id}.issubset(ids)


def test_list_highlights_discarded_only(client, db, make_highlight):
    headers = _auth_headers(db)
    rows = _seed_three_states(db, make_highlight)
    resp = client.get("/api/v2/highlights/?discarded=true", headers=headers)
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == rows["disc"].id


def test_list_highlights_mastered_only(client, db, make_highlight):
    headers = _auth_headers(db)
    rows = _seed_three_states(db, make_highlight)
    resp = client.get("/api/v2/highlights/?mastered=true", headers=headers)
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == rows["mas"].id
    assert body["results"][0]["is_mastered"] is True


def test_list_highlights_filters_combine(client, db, make_highlight):
    """favorited=true AND mastered=false should keep favorites that
    aren't also mastered."""
    headers = _auth_headers(db)
    fav_only = make_highlight(text="fav", is_favorited=True)
    fav_and_mas = make_highlight(text="fav+mas", is_favorited=True)
    fav_and_mas.is_mastered = True
    db.add(fav_and_mas)
    db.commit()

    resp = client.get(
        "/api/v2/highlights/?favorited=true&mastered=false", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["id"] == fav_only.id


def test_list_highlights_pagination_preserves_filter(client, db, make_highlight):
    headers = _auth_headers(db)
    for i in range(75):
        make_highlight(text=f"f{i}", is_favorited=True)
    resp = client.get("/api/v2/highlights/?favorited=true&page_size=50", headers=headers)
    body = resp.json()
    assert body["count"] == 75
    assert body["next"] and "favorited=true" in body["next"]
    assert "page=2" in body["next"]


# ── /api/v2/books/ filters ───────────────────────────────────────────────


def test_list_books_filter_by_author_exact(client, db, make_highlight, make_book):
    headers = _auth_headers(db)
    a = make_book(title="Solo by A", author="Author A")
    b = make_book(title="Solo by B", author="Author B")
    make_highlight(book=a)
    make_highlight(book=b)

    resp = client.get(
        "/api/v2/books/?author=Author+A", headers=headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["author"] == "Author A"


def test_list_books_filter_substring(client, db, make_highlight, make_book):
    """?q= should match against title or author, case-insensitive."""
    headers = _auth_headers(db)
    a = make_book(title="The Stoic Way", author="Marcus")
    b = make_book(title="Other Book", author="Marcus")
    c = make_book(title="Unrelated", author="Other Author")
    make_highlight(book=a); make_highlight(book=b); make_highlight(book=c)

    # Title hit
    body = client.get("/api/v2/books/?q=stoic", headers=headers).json()
    assert {r["title"] for r in body["results"]} == {"The Stoic Way"}

    # Author hit (matches both Marcus books)
    body = client.get("/api/v2/books/?q=marcus", headers=headers).json()
    assert {r["title"] for r in body["results"]} == {"The Stoic Way", "Other Book"}


def test_list_books_pagination_preserves_q(client, db, make_highlight, make_book):
    headers = _auth_headers(db)
    for i in range(60):
        b = make_book(title=f"Stoic Book {i}", author="X")
        make_highlight(book=b)
    body = client.get(
        "/api/v2/books/?q=stoic&page_size=50", headers=headers
    ).json()
    assert body["count"] == 60
    assert "q=stoic" in (body["next"] or "")
