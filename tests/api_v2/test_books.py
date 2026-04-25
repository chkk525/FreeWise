"""Integration tests for /api/v2/books/."""

from __future__ import annotations

from app.models import ApiToken


def _auth_headers(db, value: str = "tk") -> dict[str, str]:
    db.add(ApiToken(token=value, name="ext", user_id=1))
    db.commit()
    return {"Authorization": f"Token {value}"}


def test_books_empty(client, db):
    headers = _auth_headers(db)
    resp = client.get("/api/v2/books/", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"count": 0, "next": None, "previous": None, "results": []}


def test_books_lists_only_books_with_user_highlights(client, db, make_book):
    headers = _auth_headers(db)
    # Book without any highlights — should NOT appear.
    make_book(title="Empty Book", author="X")

    # Create two books via the API; both should appear.
    client.post(
        "/api/v2/highlights/",
        headers=headers,
        json={
            "highlights": [
                {"text": "h1", "title": "First", "author": "A"},
                {"text": "h2", "title": "First", "author": "A"},
                {"text": "h3", "title": "Second", "author": "B"},
            ]
        },
    )

    resp = client.get("/api/v2/books/", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    titles = [b["title"] for b in body["results"]]
    assert "Empty Book" not in titles
    assert set(titles) == {"First", "Second"}

    # Newest first by id desc — "Second" was created after "First".
    assert titles[0] == "Second"

    # num_highlights is correct.
    by_title = {b["title"]: b for b in body["results"]}
    assert by_title["First"]["num_highlights"] == 2
    assert by_title["Second"]["num_highlights"] == 1


def test_books_unauthenticated(client):
    resp = client.get("/api/v2/books/")
    assert resp.status_code == 401


def test_books_pagination(client, db):
    headers = _auth_headers(db)
    payload = {
        "highlights": [
            {"text": f"h{i}", "title": f"Book {i:02d}", "author": "A"}
            for i in range(55)
        ]
    }
    resp = client.post("/api/v2/highlights/", headers=headers, json=payload)
    assert resp.status_code == 201

    resp = client.get("/api/v2/books/?page_size=50", headers=headers)
    body = resp.json()
    assert body["count"] == 55
    assert len(body["results"]) == 50
    assert body["next"] is not None
    assert "page=2" in body["next"]

    resp = client.get("/api/v2/books/?page=2&page_size=50", headers=headers)
    body = resp.json()
    assert len(body["results"]) == 5
    assert body["next"] is None
    assert body["previous"] is not None
