"""Test the CLI argv handling end-to-end with stdout capture."""

from __future__ import annotations

import json
from unittest.mock import patch

from sqlmodel import Session

from conftest import _test_engine
from app.models import Highlight, Book

from freewise_cli import main as cli_main


def _add_highlight(text: str, **kwargs) -> int:
    with Session(_test_engine) as s:
        b = s.get(Book, 1)
        if b is None:
            b = Book(id=1, title="T", author="A")
            s.add(b); s.commit()
        h = Highlight(book_id=1, user_id=1, text=text, **kwargs)
        s.add(h); s.commit(); s.refresh(h)
        return h.id


def _run(argv, http_client, auth_token, capsys):
    """Drive the CLI argv handler with the in-process TestClient injected."""
    from freewise_cli import main as m

    real_client_factory = m._client_from_args

    def patched(args):
        c = real_client_factory(args)
        c.http = http_client
        c.token = auth_token
        c.url = "http://testserver"
        return c

    with patch.object(m, "_client_from_args", patched):
        rc = cli_main.main(argv)
    captured = capsys.readouterr()
    return rc, captured.out, captured.err


# ── search / recent / show / stats ─────────────────────────────────────────


def test_search_text_output(http_client, auth_token, capsys):
    _add_highlight("the brown fox jumps")
    _add_highlight("nothing related")
    rc, out, _ = _run(["search", "brown"], http_client, auth_token, capsys)
    assert rc == 0
    assert "1 match" in out
    assert "brown fox" in out


def test_search_json_output(http_client, auth_token, capsys):
    _add_highlight("alpha")
    rc, out, _ = _run(["--json", "search", "alpha"], http_client, auth_token, capsys)
    assert rc == 0
    body = json.loads(out)
    assert body["count"] == 1


def test_recent_output(http_client, auth_token, capsys):
    _add_highlight("first")
    _add_highlight("second")
    rc, out, _ = _run(["recent", "--limit", "10"], http_client, auth_token, capsys)
    assert rc == 0
    assert "first" in out
    assert "second" in out


def test_show_full_detail(http_client, auth_token, capsys):
    hid = _add_highlight("show me", note="my note")
    rc, out, _ = _run(["show", str(hid)], http_client, auth_token, capsys)
    assert rc == 0
    assert "show me" in out
    assert "my note" in out


def test_stats_output(http_client, auth_token, capsys):
    _add_highlight("a"); _add_highlight("b", is_favorited=True)
    rc, out, _ = _run(["stats"], http_client, auth_token, capsys)
    assert rc == 0
    assert "highlights total:" in out


# ── note / favorite / unfavorite / discard / restore ──────────────────────


def test_note_sets_text(http_client, auth_token, capsys):
    hid = _add_highlight("x")
    rc, out, _ = _run(["note", str(hid), "fresh"], http_client, auth_token, capsys)
    assert rc == 0
    assert "note updated" in out
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).note == "fresh"


def test_favorite_then_unfavorite(http_client, auth_token, capsys):
    hid = _add_highlight("x")
    _run(["favorite", str(hid)], http_client, auth_token, capsys)
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).is_favorited is True
    _run(["unfavorite", str(hid)], http_client, auth_token, capsys)
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).is_favorited is False


def test_discard_and_restore(http_client, auth_token, capsys):
    hid = _add_highlight("x")
    _run(["discard", str(hid)], http_client, auth_token, capsys)
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).is_discarded is True
    _run(["restore", str(hid)], http_client, auth_token, capsys)
    with Session(_test_engine) as s:
        assert s.get(Highlight, hid).is_discarded is False


# ── add (manual capture) ──────────────────────────────────────────────────


def test_add_creates_highlight(http_client, auth_token, capsys):
    rc, out, _ = _run(
        ["add", "--text", "captured from CLI", "--book", "From CLI", "--author", "Me"],
        http_client, auth_token, capsys,
    )
    assert rc == 0
    assert "created 1 highlight" in out
    with Session(_test_engine) as s:
        rows = s.exec(__import__("sqlmodel").select(Highlight)).all()
        assert any(h.text == "captured from CLI" for h in rows)
