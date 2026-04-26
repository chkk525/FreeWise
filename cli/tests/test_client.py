"""End-to-end tests for the CLI's HTTP client against the in-process FreeWise app."""

from __future__ import annotations

import pytest
from sqlmodel import Session

from conftest import _test_engine
from app.models import Highlight, Book

from freewise_cli.client import FreewiseError


def _add_book_with_highlights(*hl_kwargs):
    with Session(_test_engine) as s:
        b = Book(title="Test Book", author="Test Author")
        s.add(b); s.commit(); s.refresh(b)
        for kw in hl_kwargs:
            s.add(Highlight(book_id=b.id, user_id=1, **kw))
        s.commit()


def test_auth_check_ok(cli_client):
    cli_client.auth_check()  # 204 → returns None


def test_auth_check_unauthorized(http_client):
    from freewise_cli.client import Client
    bad = Client(url="http://testserver", token="not-a-real-token", http=http_client)
    with pytest.raises(FreewiseError) as ei:
        bad.auth_check()
    assert ei.value.status == 401


def test_search(cli_client):
    _add_book_with_highlights({"text": "the brown fox jumps"}, {"text": "unrelated"})
    body = cli_client.search("brown fox")
    assert body["count"] == 1
    assert body["results"][0]["text"] == "the brown fox jumps"


def test_list_highlights(cli_client):
    _add_book_with_highlights({"text": "a"}, {"text": "b"}, {"text": "c"})
    body = cli_client.list_highlights(page_size=2)
    assert body["count"] == 3
    assert len(body["results"]) == 2


def test_get_and_patch_highlight(cli_client):
    _add_book_with_highlights({"text": "patch me"})
    listing = cli_client.list_highlights()
    hid = listing["results"][0]["id"]

    detail = cli_client.get_highlight(hid)
    assert detail["text"] == "patch me"

    patched = cli_client.patch_highlight(hid, note="from CLI", is_favorited=True)
    assert patched["note"] == "from CLI"
    assert patched["is_favorited"] is True


def test_stats(cli_client):
    _add_book_with_highlights(
        {"text": "a"}, {"text": "b", "is_favorited": True},
        {"text": "c", "is_discarded": True},
    )
    s = cli_client.stats()
    assert s["highlights_total"] == 3
    assert s["highlights_active"] == 2
    assert s["highlights_favorited"] == 1
    assert s["books_total"] == 1


def test_create_highlight(cli_client):
    body = cli_client.create_highlight(
        text="manual capture", title="New Book", author="A", note="ctx",
    )
    assert body["created"] == 1
    assert body["skipped_duplicates"] == 0


def test_list_books(cli_client):
    _add_book_with_highlights({"text": "x"})
    body = cli_client.list_books()
    assert body["count"] == 1
    assert body["results"][0]["title"] == "Test Book"
    assert body["results"][0]["num_highlights"] == 1


def test_backup_streams_to_disk(cli_client, tmp_path):
    """The CLI backup() method writes a real SQLite blob to disk."""
    _add_book_with_highlights({"text": "round-trip me"})
    out = tmp_path / "snap.sqlite"
    written = cli_client.backup(str(out))
    assert written > 0
    blob = out.read_bytes()
    assert blob[:16] == b"SQLite format 3\x00"
    # Round-trip: the highlight made it into the snapshot.
    import sqlite3
    conn = sqlite3.connect(str(out))
    try:
        rows = conn.execute("SELECT text FROM highlight").fetchall()
    finally:
        conn.close()
    assert any(r[0] == "round-trip me" for r in rows)
