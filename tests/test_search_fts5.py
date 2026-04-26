"""Tests for the FTS5 substring index added in U91.

The migration in app.db.ensure_schema_migrations attempts to create a
trigram-tokenized FTS5 virtual table. If FTS5 + trigram are compiled
into the linked SQLite (true on every modern build) the search routes
prefer MATCH over LIKE for queries >= 3 chars. These tests confirm:

  - the migration sets FTS5_AVAILABLE
  - triggers keep highlight_fts in sync on INSERT / UPDATE / DELETE
  - the search route uses the index for >=3-char queries
  - Japanese text round-trips via trigram
  - < 3 char queries fall back to LIKE
"""

from __future__ import annotations

from sqlmodel import text


class TestFTS5Migration:
    def test_flag_is_set_after_migration(self):
        # The autouse fixture in conftest already calls
        # ensure_schema_migrations on the test engine, so this is a
        # post-condition check.
        from app.db import FTS5_AVAILABLE
        assert FTS5_AVAILABLE is True, (
            "FTS5 trigram should be available in the test SQLite"
        )

    def test_index_is_in_sync_after_insert(self, db, make_highlight):
        h = make_highlight(text="needle in the haystack")
        rows = db.exec(text(
            "SELECT rowid FROM highlight_fts WHERE highlight_fts MATCH 'needle'"
        )).all()
        assert (h.id,) in rows

    def test_index_updates_on_text_change(self, db, make_highlight):
        h = make_highlight(text="original wording here")
        h.text = "completely replaced text now"
        db.add(h); db.commit()
        # Old text gone
        rows = db.exec(text(
            "SELECT rowid FROM highlight_fts WHERE highlight_fts MATCH 'original'"
        )).all()
        assert (h.id,) not in rows
        # New text present
        rows = db.exec(text(
            "SELECT rowid FROM highlight_fts WHERE highlight_fts MATCH 'replaced'"
        )).all()
        assert (h.id,) in rows

    def test_index_drops_on_delete(self, db, make_highlight):
        h = make_highlight(text="ephemeral content")
        hid = h.id
        db.delete(h); db.commit()
        rows = db.exec(text(
            "SELECT rowid FROM highlight_fts WHERE highlight_fts MATCH 'ephemeral'"
        )).all()
        assert (hid,) not in rows


class TestSearchUsesFTS5:
    def test_html_search_finds_match_via_fts5(self, client, make_highlight):
        make_highlight(text="the quick brown fox jumps over the lazy dog")
        make_highlight(text="completely unrelated content")
        r = client.get("/highlights/ui/search?q=brown fox")
        assert r.status_code == 200
        assert "quick brown fox" in r.text
        assert "completely unrelated" not in r.text

    def test_search_handles_japanese_via_trigram(self, client, make_highlight):
        # Trigram works for any language so a Japanese 3+ char query
        # should match without MeCab/ICU.
        make_highlight(text="見るから始まる物語があった")
        make_highlight(text="まったく関係ない文章")
        r = client.get("/highlights/ui/search?q=始まる")
        assert r.status_code == 200
        assert "始まる物語" in r.text
        assert "関係ない" not in r.text

    def test_short_query_uses_like_fallback(self, client, make_highlight):
        # 1-2 char queries can't form a trigram; the route must fall
        # back to LIKE so they still work (rare but matters for CJK
        # particles or single-letter codes).
        make_highlight(text="contains z somewhere")
        make_highlight(text="no match here")
        r = client.get("/highlights/ui/search?q=z")
        assert r.status_code == 200
        assert "contains z somewhere" in r.text
        assert "no match here" not in r.text

    def test_quote_in_query_does_not_break_match(self, client, make_highlight):
        # User types a literal " — must be doubled inside the FTS5
        # phrase so the parser stays happy.
        make_highlight(text='he said "hello there"')
        make_highlight(text="bare other")
        r = client.get('/highlights/ui/search?q=said "hello')
        # Should not 500; either matches or returns 0 results, both fine.
        assert r.status_code == 200


class TestApiSearchUsesFTS5:
    def test_api_v2_search_uses_index(self, client, db, make_highlight):
        import hashlib
        from app.models import ApiToken
        token = ApiToken(
            token_prefix="good-token-prefi"[:16],
            token_hash=hashlib.sha256(b"good-token").hexdigest(),
            name="t", user_id=1,
        )
        db.add(token); db.commit()
        make_highlight(text="api-side-trigram-test phrase")
        r = client.get(
            "/api/v2/highlights/search",
            params={"q": "trigram"},
            headers={"Authorization": "Token good-token"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["count"] == 1
        assert "trigram" in body["results"][0]["text"]
