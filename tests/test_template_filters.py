"""Tests for app.template_filters — note autolinking + XSS safety."""

from __future__ import annotations

from app.template_filters import autolink


class TestAutolink:
    def test_empty_returns_empty_markup(self):
        assert str(autolink("")) == ""
        assert str(autolink(None)) == ""

    def test_plain_text_is_escaped(self):
        out = str(autolink("hello <script>alert(1)</script>"))
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_bare_url_becomes_anchor(self):
        out = str(autolink("see https://example.com for details"))
        assert '<a href="https://example.com"' in out
        assert 'target="_blank"' in out
        assert 'rel="noopener nofollow"' in out
        assert ">https://example.com</a>" in out
        # Surrounding text preserved.
        assert "see " in out and " for details" in out

    def test_javascript_scheme_not_linked(self):
        out = str(autolink("danger javascript:alert(1) here"))
        assert "<a " not in out
        assert "javascript:alert(1)" in out  # escaped + not anchored

    def test_data_scheme_not_linked(self):
        out = str(autolink("data:text/html,<script>x</script> bad"))
        assert "<a " not in out
        assert "&lt;script&gt;" in out

    def test_url_with_query_string(self):
        out = str(autolink("https://example.com/path?a=1&b=2"))
        # & must be escaped inside both href and label
        assert 'href="https://example.com/path?a=1&amp;b=2"' in out

    def test_quote_in_text_cannot_break_attribute(self):
        out = str(autolink('try " https://example.com" '))
        assert '\\"' not in out
        # The bare quote must be escaped.
        assert "&#34;" in out or "&quot;" in out

    def test_url_terminator_does_not_consume_following_html(self):
        # If text contains a URL followed by HTML chars, the URL match
        # must stop at the < — not slurp into a fake tag.
        out = str(autolink("https://example.com<bad>tail"))
        assert 'href="https://example.com"' in out
        assert "&lt;bad&gt;" in out

    def test_multiple_urls_in_one_string(self):
        out = str(autolink("a https://a.com b https://b.com c"))
        assert out.count("<a ") == 2

    def test_returns_markup_not_str(self):
        from markupsafe import Markup
        assert isinstance(autolink("plain"), Markup)


class TestNoteRendersInTemplate:
    """End-to-end: a note with a URL renders as a clickable anchor in the
    highlight permalink page. Catches a missing register() call."""

    def test_url_in_note_becomes_link_on_permalink(self, client, make_highlight):
        h = make_highlight(text="x", note="ref https://example.com here")
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        assert '<a href="https://example.com"' in resp.text

    def test_linebreaks_preserved_via_css(self, client, make_highlight):
        # The CSS class is what preserves \n; just check it's emitted.
        h = make_highlight(text="x", note="line1\nline2")
        resp = client.get(f"/highlights/ui/h/{h.id}")
        assert resp.status_code == 200
        assert "whitespace-pre-wrap" in resp.text
