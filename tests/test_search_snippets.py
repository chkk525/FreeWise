"""Tests for FTS5 snippet rendering on /highlights/ui/search and
/api/v2/highlights/search."""
from __future__ import annotations

import hashlib

from app.models import ApiToken
from app.services.search_snippet import (
    SNIPPET_OPEN_SENTINEL,
    SNIPPET_CLOSE_SENTINEL,
    fetch_snippets,
    render,
)


# ── Sentinel safety + render helper ───────────────────────────────────────


def test_render_escapes_html_then_replaces_sentinels():
    raw = (
        f"a <script>alert(1)</script> b "
        f"{SNIPPET_OPEN_SENTINEL}match{SNIPPET_CLOSE_SENTINEL} c"
    )
    out = render(raw)
    # Original HTML must be escaped.
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    # Sentinels become real <mark> markup.
    assert "<mark" in out
    assert "</mark>" in out
    # Escaped sentinels must NOT survive in output.
    assert SNIPPET_OPEN_SENTINEL not in out
    assert SNIPPET_CLOSE_SENTINEL not in out


def test_render_handles_empty_string():
    assert render("") == ""


# ── Service: fetch_snippets via real FTS5 ────────────────────────────────


def test_fetch_snippets_marks_match(db, make_highlight):
    h = make_highlight(text="The quick brown fox jumps over the lazy dog")
    snippets = fetch_snippets(
        db,
        rowids=[h.id],
        match_query='"brown fox"',
    )
    assert h.id in snippets
    snip = snippets[h.id]
    assert "<mark" in snip
    assert "brown fox" in snip


def test_fetch_snippets_japanese_match(db, make_highlight):
    h = make_highlight(text="経済学の基本原理を学ぶことは重要だ")
    snippets = fetch_snippets(
        db,
        rowids=[h.id],
        match_query='"経済学"',
    )
    assert h.id in snippets
    assert "<mark" in snippets[h.id]
    assert "経済学" in snippets[h.id]


def test_fetch_snippets_returns_empty_for_no_match(db, make_highlight):
    h = make_highlight(text="nothing about that subject here")
    out = fetch_snippets(db, rowids=[h.id], match_query='"unrelated"')
    assert out == {}


def test_fetch_snippets_empty_rowid_list_short_circuits(db):
    assert fetch_snippets(db, rowids=[], match_query='"x"') == {}


# ── HTML route ────────────────────────────────────────────────────────────


def test_html_search_renders_mark_tag_around_match(client, make_highlight):
    make_highlight(text="The quick brown fox jumps over the lazy dog")
    resp = client.get("/highlights/ui/search?q=brown%20fox")
    assert resp.status_code == 200
    body = resp.text
    # Sentinels must NOT leak through.
    assert SNIPPET_OPEN_SENTINEL not in body
    assert SNIPPET_CLOSE_SENTINEL not in body
    # The hit context is wrapped in <mark>.
    assert "<mark" in body
    # And the matched substring is still present.
    assert "brown fox" in body


def test_html_search_falls_back_to_plain_text_on_short_query(client, make_highlight):
    """2-char queries take the LIKE path; the template must NOT inject
    a snippet (no <mark>) and must still render the highlight text."""
    make_highlight(text="物語のはじまりの一節を覚えておく")
    resp = client.get("/highlights/ui/search?q=%E7%89%A9%E8%AA%9E")  # 物語
    assert resp.status_code == 200
    # Highlight rendered.
    assert "物語のはじまり" in resp.text


def test_html_search_xss_resistant_when_highlight_contains_html(client, make_highlight):
    """User-pasted HTML inside a highlight must arrive in the response
    HTML-escaped, not as live markup. The page itself ships <script>
    tags for htmx etc.; what we care about is the *user-authored*
    payload `<script>alert(1)</script>`, which must NEVER appear
    verbatim."""
    make_highlight(text="<script>alert(1)</script> ordinary content nearby")
    resp = client.get("/highlights/ui/search?q=ordinary")
    assert resp.status_code == 200
    # The user payload, in raw form, must not exist anywhere on the page.
    assert "<script>alert(1)</script>" not in resp.text
    # And the escaped form must be present (i.e. the highlight rendered).
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


# ── API route ─────────────────────────────────────────────────────────────


def _seed_token(db) -> str:
    raw = "snippet-token"
    db.add(
        ApiToken(
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            token_prefix=raw[:16],
            name="snip",
            user_id=1,
            scopes="kindle:import,highlights:read,highlights:write,books:read",
        )
    )
    db.commit()
    return raw


def test_api_search_returns_snippet_field(client, db, make_highlight):
    raw = _seed_token(db)
    make_highlight(text="A passage about stoicism and acceptance")
    resp = client.get(
        "/api/v2/highlights/search?q=stoicism",
        headers={"Authorization": f"Token {raw}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["count"] == 1
    item = body["results"][0]
    assert item["snippet"] is not None
    assert "<mark" in item["snippet"]
    assert "stoicism" in item["snippet"]


def test_api_search_snippet_is_null_on_short_query(client, db, make_highlight):
    raw = _seed_token(db)
    make_highlight(text="物語のはじまりの一節")
    # 2-char query → LIKE fallback → no snippet.
    resp = client.get(
        "/api/v2/highlights/search?q=%E7%89%A9%E8%AA%9E",
        headers={"Authorization": f"Token {raw}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["results"][0]["snippet"] is None


def test_api_search_snippet_japanese_match(client, db, make_highlight):
    raw = _seed_token(db)
    make_highlight(text="経済学の基本原理について説明する")
    resp = client.get(
        "/api/v2/highlights/search?q=%E7%B5%8C%E6%B8%88%E5%AD%A6",  # 経済学
        headers={"Authorization": f"Token {raw}"},
    )
    assert resp.status_code == 200
    item = resp.json()["results"][0]
    assert item["snippet"] is not None
    assert "<mark" in item["snippet"]
    assert "経済学" in item["snippet"]
