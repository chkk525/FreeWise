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
