"""Tests for the quote-card OG image (U98)."""

from __future__ import annotations

import io

from PIL import Image

from app.services.quote_card import (
    HEIGHT,
    WIDTH,
    render_quote_png,
    wrap_for_card,
)


# ── Wrap helper ─────────────────────────────────────────────────────────


class TestWrap:
    def test_empty_returns_no_lines(self):
        assert wrap_for_card("") == []
        assert wrap_for_card(None) == []  # type: ignore[arg-type]

    def test_short_ascii_one_line(self):
        lines = wrap_for_card("hello world")
        assert lines == ["hello world"]

    def test_long_ascii_wraps(self):
        text = ("Wisdom begins in wonder. " * 10).strip()
        lines = wrap_for_card(text)
        assert len(lines) > 1
        # No line should exceed the ASCII width by much (textwrap honors it).
        for ln in lines:
            assert len(ln) <= 60  # generous slack for word-boundary slop

    def test_overflow_truncates_with_ellipsis(self):
        # 50 lines worth of content; should clamp to MAX_LINES (9) with …
        text = "alpha bravo charlie delta echo foxtrot golf hotel " * 50
        lines = wrap_for_card(text)
        from app.services.quote_card import MAX_LINES
        assert len(lines) == MAX_LINES
        assert lines[-1].endswith("…")

    def test_japanese_uses_char_based_wrap(self):
        text = "見るから始まる物語があった" * 5
        lines = wrap_for_card(text)
        # Each line should be ≤ CJK_LINE_CHARS chars (the slicing window).
        from app.services.quote_card import CJK_LINE_CHARS
        for ln in lines:
            assert len(ln) <= CJK_LINE_CHARS

    def test_mixed_cjk_dominant_text_uses_cjk_wrap(self):
        # Mostly Japanese + a few English words → CJK wrap.
        text = "今日は良い天気です。Hello world。明日は雨が降るでしょう。"
        lines = wrap_for_card(text)
        # Just confirm we get *something* without crashing.
        assert lines


# ── PNG render ──────────────────────────────────────────────────────────


class TestRenderQuotePng:
    def _decode(self, png_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(png_bytes))

    def test_returns_valid_png(self):
        png = render_quote_png("Some highlight text")
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_dimensions_match_twitter_large_image(self):
        png = render_quote_png("body")
        img = self._decode(png)
        assert img.size == (WIDTH, HEIGHT)
        assert img.size == (1200, 630)

    def test_with_book_attribution(self):
        png = render_quote_png(
            "Knowledge is power",
            book_title="Sapiens",
            book_author="Yuval Noah Harari",
        )
        # Just sanity-check it's a clean PNG; pixel-level assertions on
        # rasterized text are too brittle across font availability.
        img = self._decode(png)
        assert img.mode == "RGB"
        assert img.size == (WIDTH, HEIGHT)

    def test_without_book(self):
        # No attribution → still a valid card.
        png = render_quote_png("standalone quote without a book")
        img = self._decode(png)
        assert img.size == (WIDTH, HEIGHT)

    def test_japanese_text_does_not_crash(self):
        png = render_quote_png("見るから始まる物語があった", book_title="本", book_author="著者")
        img = self._decode(png)
        assert img.size == (WIDTH, HEIGHT)

    def test_huge_input_clamps_via_wrap(self):
        # 5KB of text — wrap_for_card caps at MAX_LINES, so the render
        # is bounded regardless of input size.
        png = render_quote_png("hello " * 1000, book_title="t")
        img = self._decode(png)
        assert img.size == (WIDTH, HEIGHT)


# ── Endpoint ────────────────────────────────────────────────────────────


class TestQuoteImageEndpoint:
    def test_404_for_unknown_id(self, client):
        r = client.get("/highlights/ui/h/99999/quote.png")
        assert r.status_code == 404

    def test_returns_png_with_cache_headers(self, client, make_highlight, make_book):
        book = make_book(title="Sapiens", author="Yuval Noah Harari")
        h = make_highlight(text="History helps us see further", book=book)
        r = client.get(f"/highlights/ui/h/{h.id}/quote.png")
        assert r.status_code == 200
        assert r.headers["content-type"] == "image/png"
        assert "max-age=" in r.headers.get("cache-control", "")
        # Real PNG bytes
        assert r.content[:8] == b"\x89PNG\r\n\x1a\n"
        # Renders at the spec dimensions
        img = Image.open(io.BytesIO(r.content))
        assert img.size == (1200, 630)

    def test_no_auth_required(self, client, make_highlight):
        # Public, like /healthz / /metrics — no Authorization header.
        h = make_highlight(text="public highlight")
        r = client.get(f"/highlights/ui/h/{h.id}/quote.png")
        assert r.status_code == 200


# ── Permalink wires the image into og:image ─────────────────────────────


class TestPermalinkImageMeta:
    def test_og_image_url_in_permalink(self, client, make_highlight):
        h = make_highlight(text="x")
        r = client.get(f"/highlights/ui/h/{h.id}")
        assert r.status_code == 200
        assert f'<meta property="og:image" content="/highlights/ui/h/{h.id}/quote.png">' in r.text
        assert '<meta property="og:image:width" content="1200">' in r.text
        assert '<meta property="og:image:height" content="630">' in r.text
        assert f'<meta name="twitter:image" content="/highlights/ui/h/{h.id}/quote.png">' in r.text
        assert '<meta name="twitter:card" content="summary_large_image">' in r.text
