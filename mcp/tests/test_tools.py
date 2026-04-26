"""Behavior tests for each MCP tool.

We import the tool callables directly. FastMCP wraps each function so the
returned `tool` object exposes the original via ``.fn``. To stay independent
of that wrapper, we re-import the module's bare functions through the module
attributes (FastMCP doesn't replace them on the module).
"""

from __future__ import annotations

import json

from sqlmodel import Session, select

from conftest import _test_engine
from app.models import Highlight, Book

import freewise_mcp.server as server


# FastMCP's @mcp.tool() in 1.x registers the function with the FastMCP instance
# and returns the original callable unchanged — so we can invoke each tool
# directly without unwrapping.
SEARCH = server.freewise_search
RECENT = server.freewise_recent
SHOW = server.freewise_show
STATS = server.freewise_stats
BOOKS = server.freewise_books
SET_NOTE = server.freewise_set_note
FAVORITE = server.freewise_favorite
DISCARD = server.freewise_discard
ADD = server.freewise_add
TAG_LIST = server.freewise_tag_list
TAG_ADD = server.freewise_tag_add
TAG_REMOVE = server.freewise_tag_remove


def _add(text: str, **kwargs) -> int:
    with Session(_test_engine) as s:
        b = s.get(Book, 1)
        if b is None:
            b = Book(id=1, title="T", author="A")
            s.add(b); s.commit()
        h = Highlight(book_id=1, user_id=1, text=text, **kwargs)
        s.add(h); s.commit(); s.refresh(h)
        return h.id


# ── Read tools ────────────────────────────────────────────────────────────


def test_search_returns_json_with_matches(patched_client):
    _add("the brown fox jumps")
    _add("nothing related")
    out = json.loads(SEARCH("brown fox"))
    assert out["count"] == 1
    assert "brown fox" in out["results"][0]["text"]


def test_search_returns_error_object_on_failure(patched_client, monkeypatch):
    """If the underlying client raises FreewiseError, the tool wraps it in JSON."""
    from freewise_cli.client import FreewiseError, Client

    class BoomClient(Client):
        def search(self, *_, **__): raise FreewiseError(500, "boom")

    monkeypatch.setattr(server, "_client", lambda: BoomClient(url="http://x", token="t"))
    out = json.loads(SEARCH("x"))
    assert "error" in out
    assert "boom" in out["error"]


def test_tool_wraps_arbitrary_exceptions_as_json(patched_client, monkeypatch):
    """Non-FreewiseError exceptions (transport/config) must also return structured
    JSON instead of breaking the MCP session. Lock this in — without the broad
    fallback in _call(), the agent sees a hard MCP protocol error."""
    from freewise_cli.client import Client

    class NetworkErrorClient(Client):
        def stats(self): raise ConnectionError("server unreachable")

    monkeypatch.setattr(server, "_client", lambda: NetworkErrorClient(url="x", token="t"))
    out = json.loads(STATS())
    assert "error" in out
    assert "ConnectionError" in out["error"]
    assert "server unreachable" in out["error"]


def test_recent_returns_newest_first(patched_client):
    _add("first")
    _add("second")
    out = json.loads(RECENT(limit=10))
    assert out["count"] == 2
    # Server orders by id desc (newest first)
    assert out["results"][0]["text"] == "second"


def test_show_returns_full_detail(patched_client):
    hid = _add("show me", note="my note", is_favorited=True)
    out = json.loads(SHOW(hid))
    assert out["id"] == hid
    assert out["text"] == "show me"
    assert out["note"] == "my note"
    assert out["is_favorited"] is True


def test_stats_returns_counts(patched_client):
    _add("a")
    _add("b", is_favorited=True)
    _add("c", is_discarded=True)
    out = json.loads(STATS())
    assert out["highlights_total"] == 3
    assert out["highlights_active"] == 2
    assert out["highlights_favorited"] == 1


def test_books_returns_list(patched_client):
    _add("x")
    out = json.loads(BOOKS(limit=10))
    assert out["count"] == 1
    assert out["results"][0]["title"] == "T"


# ── Write tools ───────────────────────────────────────────────────────────


def test_set_note_updates_note(patched_client):
    hid = _add("x")
    out = json.loads(SET_NOTE(hid, "fresh"))
    assert out["note"] == "fresh"
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).note == "fresh"


def test_set_note_clears_with_empty_string(patched_client):
    hid = _add("x", note="old")
    out = json.loads(SET_NOTE(hid, ""))
    assert out["note"] == ""


def test_favorite_on_then_off(patched_client):
    hid = _add("x")
    on = json.loads(FAVORITE(hid, on=True))
    assert on["is_favorited"] is True
    off = json.loads(FAVORITE(hid, on=False))
    assert off["is_favorited"] is False


def test_discard_then_restore(patched_client):
    hid = _add("x")
    out = json.loads(DISCARD(hid, on=True))
    assert out["is_discarded"] is True
    out = json.loads(DISCARD(hid, on=False))
    assert out["is_discarded"] is False


def test_discard_auto_unfavorites(patched_client):
    hid = _add("x", is_favorited=True)
    out = json.loads(DISCARD(hid, on=True))
    assert out["is_discarded"] is True
    assert out["is_favorited"] is False


def test_add_creates_highlight(patched_client):
    out = json.loads(ADD(text="captured", book="From MCP", author="Me", note="ctx"))
    assert out["created"] == 1
    with Session(_test_engine) as s:
        rows = s.exec(select(Highlight)).all()
        assert any(h.text == "captured" for h in rows)


def test_tag_add_normalizes_and_returns_list(patched_client):
    hid = _add("x")
    out = json.loads(TAG_ADD(hid, "  Python  "))
    assert out == {"tags": ["python"]}


def test_tag_add_idempotent(patched_client):
    hid = _add("x")
    TAG_ADD(hid, "ml")
    out = json.loads(TAG_ADD(hid, "ml"))
    assert out == {"tags": ["ml"]}


def test_tag_remove(patched_client):
    hid = _add("x")
    TAG_ADD(hid, "a"); TAG_ADD(hid, "b")
    out = json.loads(TAG_REMOVE(hid, "a"))
    assert out == {"tags": ["b"]}


def test_tag_list(patched_client):
    hid = _add("x")
    TAG_ADD(hid, "z"); TAG_ADD(hid, "a")
    out = json.loads(TAG_LIST(hid))
    assert out == {"tags": ["a", "z"]}


def test_search_with_tag_filter(patched_client):
    h1 = _add("alpha quote")
    _add("alpha other")
    TAG_ADD(h1, "important")
    out = json.loads(SEARCH("alpha", tag="important"))
    assert out["count"] == 1
    assert out["results"][0]["id"] == h1


def test_tool_surface_complete(patched_client):
    """Sanity: FastMCP server should have exactly the 12 expected tools registered."""
    import asyncio
    tools = asyncio.run(server.mcp.list_tools())
    names = {t.name for t in tools}
    expected = {
        "freewise_search", "freewise_recent", "freewise_show",
        "freewise_stats", "freewise_books", "freewise_set_note",
        "freewise_favorite", "freewise_discard", "freewise_add",
        "freewise_tag_list", "freewise_tag_add", "freewise_tag_remove",
    }
    assert names == expected
