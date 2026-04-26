"""
Tests for the CSV import and export functionality.

Covers: Readwise CSV import, custom CSV import, datetime parsing,
deduplication, tag handling, favorite/discard flags, and CSV export.
"""
import io
import csv
from datetime import datetime

from sqlmodel import select

from app.models import Highlight, Book, Tag, HighlightTag
from app.routers.importer import parse_readwise_datetime


# ── Datetime parsing ──────────────────────────────────────────────────────────

class TestParseReadwiseDatetime:
    """parse_readwise_datetime() handles many date formats."""

    def test_readwise_human_format(self):
        dt = parse_readwise_datetime("January 15, 2024 10:30:00 AM")
        assert dt == datetime(2024, 1, 15, 10, 30, 0)

    def test_iso_format(self):
        dt = parse_readwise_datetime("2024-01-15 10:30:00")
        assert dt == datetime(2024, 1, 15, 10, 30, 0)

    def test_iso_t_separator(self):
        dt = parse_readwise_datetime("2024-01-15T10:30:00")
        assert dt == datetime(2024, 1, 15, 10, 30, 0)

    def test_timezone_aware_stripped(self):
        dt = parse_readwise_datetime("2025-12-10 14:18:00+00:00")
        assert dt is not None
        assert dt.tzinfo is None

    def test_empty_string_returns_none(self):
        assert parse_readwise_datetime("") is None

    def test_garbage_returns_none(self):
        assert parse_readwise_datetime("not-a-date") is None

    def test_whitespace_only_returns_none(self):
        assert parse_readwise_datetime("   ") is None


# ── Readwise CSV Import ──────────────────────────────────────────────────────

def _make_readwise_csv(rows: list[dict]) -> io.BytesIO:
    """Build a Readwise-format CSV in memory."""
    output = io.StringIO()
    fieldnames = [
        "Highlight", "Book Title", "Book Author", "Amazon Book ID",
        "Note", "Color", "Tags", "Location Type", "Location",
        "Highlighted at", "Document tags",
    ]
    # Add extended columns if any row has them
    if any("is_favorited" in r for r in rows):
        fieldnames += ["is_favorited", "is_discarded"]

    writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    buf = io.BytesIO(output.getvalue().encode("utf-8"))
    buf.name = "import.csv"
    return buf


class TestReadwiseImport:
    """POST /import/ui/readwise — Readwise CSV import."""

    def test_basic_import(self, client, db):
        csv_file = _make_readwise_csv([{
            "Highlight": "Knowledge is power",
            "Book Title": "Meditations",
            "Book Author": "Marcus Aurelius",
            "Highlighted at": "2024-01-15 10:00:00",
        }])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        assert "1 highlights" in resp.text

        h = db.exec(select(Highlight)).first()
        assert h is not None
        assert h.text == "Knowledge is power"
        book = db.get(Book, h.book_id)
        assert book.title == "Meditations"
        assert book.author == "Marcus Aurelius"

    def test_deduplication(self, client, db):
        csv_file = _make_readwise_csv([
            {"Highlight": "Same text", "Book Title": "Book A", "Book Author": "A"},
            {"Highlight": "Same text", "Book Title": "Book A", "Book Author": "A"},
        ])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        highlights = db.exec(select(Highlight)).all()
        assert len(highlights) == 1

    def test_skip_empty_highlight(self, client, db):
        csv_file = _make_readwise_csv([
            {"Highlight": "", "Book Title": "Book A", "Book Author": "A"},
            {"Highlight": "Valid", "Book Title": "Book A", "Book Author": "A"},
        ])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        highlights = db.exec(select(Highlight)).all()
        assert len(highlights) == 1

    def test_skip_header_marker_notes(self, client, db):
        csv_file = _make_readwise_csv([
            {"Highlight": "Chapter heading", "Book Title": "Book", "Book Author": "A", "Note": ".h1"},
            {"Highlight": "Sub heading", "Book Title": "Book", "Book Author": "A", "Note": ".H2"},
        ])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        highlights = db.exec(select(Highlight)).all()
        assert len(highlights) == 0

    def test_tag_based_favorite(self, client, db):
        csv_file = _make_readwise_csv([{
            "Highlight": "Fav highlight",
            "Book Title": "Book",
            "Book Author": "A",
            "Tags": "favorite, philosophy",
        }])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        h = db.exec(select(Highlight)).first()
        assert h.is_favorited is True
        # "favorite" should NOT be stored as a regular tag
        tags = db.exec(select(Tag)).all()
        tag_names = [t.name for t in tags]
        assert "favorite" not in tag_names
        assert "philosophy" in tag_names

    def test_tag_based_discard(self, client, db):
        csv_file = _make_readwise_csv([{
            "Highlight": "Disc highlight",
            "Book Title": "Book",
            "Book Author": "A",
            "Tags": "discard",
        }])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        h = db.exec(select(Highlight)).first()
        assert h.is_discarded is True

    def test_extended_columns_take_precedence(self, client, db):
        csv_file = _make_readwise_csv([{
            "Highlight": "Extended",
            "Book Title": "Book",
            "Book Author": "A",
            "is_favorited": "true",
            "is_discarded": "false",
        }])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        h = db.exec(select(Highlight)).first()
        assert h.is_favorited is True
        assert h.is_discarded is False

    def test_location_parsed(self, client, db):
        csv_file = _make_readwise_csv([{
            "Highlight": "Located",
            "Book Title": "Book",
            "Book Author": "A",
            "Location Type": "page",
            "Location": "42",
        }])
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 200
        h = db.exec(select(Highlight)).first()
        assert h.location == 42
        assert h.location_type == "page"

    def test_invalid_file_extension(self, client):
        buf = io.BytesIO(b"not csv content")
        buf.name = "file.txt"
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("file.txt", buf, "text/plain")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 400

    def test_missing_highlight_column(self, client):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["Title", "Author"])
        writer.writeheader()
        writer.writerow({"Title": "X", "Author": "Y"})
        buf = io.BytesIO(output.getvalue().encode("utf-8"))
        buf.name = "bad.csv"
        resp = client.post(
            "/import/ui/readwise",
            files={"file": ("bad.csv", buf, "text/csv")},
            data={"diagnostic": "true"},
        )
        assert resp.status_code == 400

    def test_book_deduplication_across_imports(self, client, db):
        """Importing same book title/author twice should reuse the Book record."""
        for _ in range(2):
            csv_file = _make_readwise_csv([{
                "Highlight": f"HL {_}",
                "Book Title": "Reused Book",
                "Book Author": "Same Author",
            }])
            client.post(
                "/import/ui/readwise",
                files={"file": ("import.csv", csv_file, "text/csv")},
                data={"diagnostic": "true"},
            )
        books = db.exec(select(Book).where(Book.title == "Reused Book")).all()
        assert len(books) == 1


# ── CSV Export ────────────────────────────────────────────────────────────────

class TestCSVExport:
    """GET /export/csv — exporting highlights as Readwise-compatible CSV."""

    def test_export_basic(self, client, make_highlight, make_book, db):
        book = make_book(title="Export Book", author="Export Author")
        make_highlight(text="Exportable", book=book, is_favorited=True)

        resp = client.get("/export/csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        assert "attachment" in resp.headers.get("content-disposition", "")

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "Exportable"
        assert rows[0]["Book Title"] == "Export Book"
        assert rows[0]["Book Author"] == "Export Author"
        assert rows[0]["is_favorited"] == "true"
        assert rows[0]["is_discarded"] == "false"

    def test_export_no_highlights_returns_400(self, client):
        resp = client.get("/export/csv")
        assert resp.status_code == 400

    def test_export_has_all_headers(self, client, make_highlight):
        make_highlight(text="Header check")
        resp = client.get("/export/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        headers = reader.fieldnames
        expected = [
            "Highlight", "Book Title", "Book Author", "Amazon Book ID",
            "Note", "Color", "Tags", "Location Type", "Location",
            "Highlighted at", "Document tags", "is_favorited", "is_discarded",
        ]
        assert headers == expected

    def test_export_loads_tags_in_one_query(self, client, db, make_highlight):
        """Tags must be bulk-loaded — N highlights must NOT emit N tag queries."""
        h1 = make_highlight(text="With tags A")
        h2 = make_highlight(text="With tags B")
        h3 = make_highlight(text="No tags")
        # Attach two regular tags + a system tag (favorite) to h1 and h2.
        for name in ("python", "favorite", "django"):
            t = Tag(name=name)
            db.add(t); db.commit(); db.refresh(t)
            for h in (h1, h2):
                db.add(HighlightTag(highlight_id=h.id, tag_id=t.id))
        db.commit()

        resp = client.get("/export/csv")
        assert resp.status_code == 200
        reader = csv.DictReader(io.StringIO(resp.text))
        by_text = {r["Highlight"]: r for r in reader}
        # Order within Tags is insertion order from the join — both tags
        # must be present, system "favorite" filtered out.
        assert "python" in by_text["With tags A"]["Tags"]
        assert "django" in by_text["With tags A"]["Tags"]
        assert "favorite" not in by_text["With tags A"]["Tags"]
        assert by_text["No tags"]["Tags"] == ""

    def test_roundtrip_import_export(self, client, db):
        """Import → export → re-import should produce the same data."""
        csv_file = _make_readwise_csv([{
            "Highlight": "Roundtrip",
            "Book Title": "RT Book",
            "Book Author": "RT Author",
            "Note": "A note",
            "Location Type": "page",
            "Location": "7",
            "Highlighted at": "2024-06-15 12:00:00",
        }])
        client.post(
            "/import/ui/readwise",
            files={"file": ("import.csv", csv_file, "text/csv")},
            data={"diagnostic": "true"},
        )

        resp = client.get("/export/csv")
        assert resp.status_code == 200

        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "Roundtrip"
        assert rows[0]["Book Title"] == "RT Book"
        assert rows[0]["Note"] == "A note"
        assert rows[0]["Location"] == "7"
        assert rows[0]["Location Type"] == "page"
