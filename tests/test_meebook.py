"""
Tests for the Meebook / Haoqing HTML import.
"""
import io

from sqlmodel import select

from app.models import Book, Highlight
from app.utils.meebook import extract_highlights, parse_date, extract_title_author
from bs4 import BeautifulSoup


# ── Minimal Haoqing HTML fixture ─────────────────────────────────────────────

SAMPLE_HTML = """\
<html><body>
<h2>Test Book - Some Author</h2>
<div style="padding-top: 1em; padding-bottom: 1em">
  <div style="border-left: 5px solid rgb(237,108,0); padding-left:8px">2025-06-15 14:30</div>
  <div style="font-size: 12pt">First highlight text.</div>
</div>
<div style="padding-top: 1em; padding-bottom: 1em">
  <div style="border-left: 5px solid rgb(237,108,0); padding-left:8px">2025-06-15 15:00</div>
  <div style="font-size: 12pt">Second highlight text.</div>
  <table><tr><td>Note:</td><td>My note here</td></tr></table>
</div>
</body></html>
"""

CHAPTER_HEADER_HTML = """\
<html><body>
<h2>Book - Author</h2>
<div style="padding-top: 1em; padding-bottom: 1em">
  <span style="color: #48b4c1; font-weight: bold">Chapter 1</span>
</div>
<div style="padding-top: 1em; padding-bottom: 1em">
  <div style="border-left: 5px solid rgb(237,108,0); padding-left:8px">2025-01-01</div>
  <div style="font-size: 12pt">Real highlight</div>
</div>
</body></html>
"""


# ── Unit tests for utility functions ──────────────────────────────────────────

class TestExtractTitleAuthor:
    def test_title_and_author(self):
        soup = BeautifulSoup("<h2>My Book - Jane Doe</h2>", "html.parser")
        assert extract_title_author(soup) == ("My Book", "Jane Doe")

    def test_title_only(self):
        soup = BeautifulSoup("<h2>Standalone Title</h2>", "html.parser")
        assert extract_title_author(soup) == ("Standalone Title", "")

    def test_no_h2(self):
        soup = BeautifulSoup("<p>Nothing</p>", "html.parser")
        assert extract_title_author(soup) == ("", "")


class TestParseDate:
    def test_date_and_time(self):
        dt = parse_date("2025-06-15 14:30")
        assert dt is not None
        assert dt.year == 2025 and dt.month == 6 and dt.hour == 14

    def test_date_only(self):
        dt = parse_date("2025-06-15")
        assert dt is not None
        assert dt.hour == 0

    def test_empty(self):
        assert parse_date("") is None

    def test_garbage(self):
        assert parse_date("not-a-date") is None


class TestExtractHighlights:
    def test_basic_extraction(self):
        hl = extract_highlights(SAMPLE_HTML)
        assert len(hl) == 2

    def test_chronological_order(self):
        hl = extract_highlights(SAMPLE_HTML)
        # After reversal the later highlight (bottom of HTML) becomes first
        assert hl[0]["text"] == "Second highlight text."
        assert hl[1]["text"] == "First highlight text."

    def test_location_assigned(self):
        hl = extract_highlights(SAMPLE_HTML)
        assert hl[0]["location"] == 1
        assert hl[1]["location"] == 2
        assert all(h["location_type"] == "order" for h in hl)

    def test_note_extracted(self):
        hl = extract_highlights(SAMPLE_HTML)
        assert hl[0]["note"] == "My note here"
        assert hl[1]["note"] is None

    def test_title_author(self):
        hl = extract_highlights(SAMPLE_HTML)
        assert hl[0]["title"] == "Test Book"
        assert hl[0]["author"] == "Some Author"

    def test_chapter_headers_skipped(self):
        hl = extract_highlights(CHAPTER_HEADER_HTML)
        assert len(hl) == 1
        assert hl[0]["text"] == "Real highlight"

    def test_empty_html(self):
        assert extract_highlights("<html><body></body></html>") == []


# ── Integration tests via TestClient ──────────────────────────────────────────

class TestMeebookImportPage:
    def test_page_loads(self, client):
        resp = client.get("/import/ui/meebook")
        assert resp.status_code == 200
        assert "Meebook" in resp.text

    def test_import_main_shows_meebook(self, client):
        resp = client.get("/import/ui")
        assert resp.status_code == 200
        assert "Meebook" in resp.text
        assert "/import/ui/meebook" in resp.text


class TestMeebookImportUpload:
    def _upload(self, client, html, filename="export.html", diagnostic="true"):
        buf = io.BytesIO(html.encode("utf-8"))
        return client.post(
            "/import/ui/meebook",
            files={"file": (filename, buf, "text/html")},
            data={"diagnostic": diagnostic},
        )

    def test_basic_import(self, client, db):
        resp = self._upload(client, SAMPLE_HTML)
        assert resp.status_code == 200
        assert "2" in resp.text  # imported 2 highlights
        books = db.exec(select(Book)).all()
        assert len(books) == 1
        assert books[0].title == "Test Book"
        highlights = db.exec(select(Highlight)).all()
        assert len(highlights) == 2

    def test_location_type_stored(self, client, db):
        self._upload(client, SAMPLE_HTML)
        hl = db.exec(select(Highlight).order_by(Highlight.location.asc())).first()
        assert hl.location == 1
        assert hl.location_type == "order"

    def test_deduplication(self, client, db):
        self._upload(client, SAMPLE_HTML)
        self._upload(client, SAMPLE_HTML)
        assert len(db.exec(select(Highlight)).all()) == 2  # not 4

    def test_reject_non_html(self, client):
        buf = io.BytesIO(b"not html")
        resp = client.post(
            "/import/ui/meebook",
            files={"file": ("data.csv", buf, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 400

    def test_empty_html(self, client):
        resp = self._upload(client, "<html><body></body></html>")
        assert resp.status_code == 200
        assert "0" in resp.text  # 0 imported
