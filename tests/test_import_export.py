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

    def test_export_filter_favorited_only(self, client, make_highlight):
        make_highlight(text="keep me", is_favorited=True)
        make_highlight(text="not me")
        resp = client.get("/export/csv?favorited_only=true")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "keep me"

    def test_export_filter_active_only_excludes_discarded(self, client, make_highlight):
        make_highlight(text="alive")
        make_highlight(text="trashed", is_discarded=True)
        resp = client.get("/export/csv?active_only=true")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "alive"

    def test_export_filter_book_id(self, client, make_highlight, make_book):
        b1 = make_book(title="One")
        b2 = make_book(title="Two")
        make_highlight(text="from one", book=b1)
        make_highlight(text="from two", book=b2)
        resp = client.get(f"/export/csv?book_id={b1.id}")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Book Title"] == "One"

    def test_export_filter_author(self, client, make_highlight, make_book):
        a = make_book(title="A1", author="Alice")
        b = make_book(title="B1", author="Bob")
        make_highlight(text="alice quote", book=a)
        make_highlight(text="bob quote", book=b)
        resp = client.get("/export/csv?author=Alice")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Book Author"] == "Alice"

    def test_export_filter_tag(self, client, db, make_highlight):
        from app.models import Tag, HighlightTag
        h1 = make_highlight(text="ml stuff")
        h2 = make_highlight(text="other stuff")
        t = Tag(name="ml"); db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h1.id, tag_id=t.id))
        db.commit()
        resp = client.get("/export/csv?tag=ml")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "ml stuff"

    def test_export_filter_no_match_returns_400(self, client, make_highlight):
        make_highlight(text="nothing favorited")
        resp = client.get("/export/csv?favorited_only=true")
        assert resp.status_code == 400
        # Filter-specific message, not the generic empty-library one.
        assert "filters" in resp.text.lower()

    def test_export_filters_compose(self, client, db, make_highlight, make_book):
        """tag + favorited_only should AND together, not OR."""
        from app.models import Tag, HighlightTag
        b = make_book(title="X")
        h_fav_tagged = make_highlight(text="fav+tag", book=b, is_favorited=True)
        h_fav_only = make_highlight(text="fav only", book=b, is_favorited=True)
        h_tag_only = make_highlight(text="tag only", book=b)
        t = Tag(name="ml"); db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h_fav_tagged.id, tag_id=t.id))
        db.add(HighlightTag(highlight_id=h_tag_only.id, tag_id=t.id))
        db.commit()
        resp = client.get("/export/csv?tag=ml&favorited_only=true")
        assert resp.status_code == 200
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        assert len(rows) == 1
        assert rows[0]["Highlight"] == "fav+tag"


    def test_markdown_export_returns_zip(self, client, make_highlight, make_book):
        """GET /export/markdown.zip should return a ZIP with one .md per book."""
        import io as _io
        import zipfile as _zip
        b = make_book(title="My Book", author="Alice", document_tags="philosophy, stoicism")
        make_highlight(text="An important quote", note="why this matters", book=b, location=42)
        make_highlight(text="another quote", book=b)

        resp = client.get("/export/markdown.zip")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        assert "attachment" in resp.headers.get("content-disposition", "")
        zf = _zip.ZipFile(_io.BytesIO(resp.content))
        names = zf.namelist()
        assert any("My Book" in n and n.endswith(".md") for n in names)
        body = zf.read(names[0]).decode("utf-8")
        # Frontmatter is present
        assert body.startswith("---")
        assert 'title: "My Book"' in body
        assert 'author: "Alice"' in body
        assert "highlight_count: 2" in body
        # Tags appear in YAML
        assert '- "philosophy"' in body
        assert '- "stoicism"' in body
        # Blockquotes
        assert "> An important quote" in body
        assert "> another quote" in body
        # Note rendered as paragraph
        assert "why this matters" in body
        # Location surface
        assert "location 42" in body

    def test_markdown_export_excludes_discarded(self, client, make_highlight, make_book):
        b = make_book(title="Book")
        make_highlight(text="alive", book=b)
        make_highlight(text="dead", book=b, is_discarded=True)
        import io as _io, zipfile as _zip
        resp = client.get("/export/markdown.zip")
        assert resp.status_code == 200
        body = _zip.ZipFile(_io.BytesIO(resp.content)).read("Book.md").decode("utf-8")
        assert "alive" in body
        assert "dead" not in body
        assert "highlight_count: 1" in body

    def test_markdown_export_400_when_empty(self, client):
        resp = client.get("/export/markdown.zip")
        assert resp.status_code == 400

    def test_markdown_export_safe_filename(self, client, make_highlight, make_book):
        """Filenames must strip OS-unsafe chars but keep unicode."""
        import io as _io, zipfile as _zip
        b = make_book(title='C/O \\Slash:Title?*"<>|')
        make_highlight(text="x", book=b)
        resp = client.get("/export/markdown.zip")
        assert resp.status_code == 200
        names = _zip.ZipFile(_io.BytesIO(resp.content)).namelist()
        assert any(n.endswith(".md") for n in names)
        for ch in '\\/:*?"<>|':
            assert not any(ch in n for n in names)

    def test_markdown_export_handles_collision(self, client, make_highlight, make_book):
        """Two books with the same title must produce distinct .md filenames."""
        import io as _io, zipfile as _zip
        b1 = make_book(title="Same Name")
        b2 = make_book(title="Same Name")
        make_highlight(text="a", book=b1)
        make_highlight(text="b", book=b2)
        resp = client.get("/export/markdown.zip")
        assert resp.status_code == 200
        names = _zip.ZipFile(_io.BytesIO(resp.content)).namelist()
        # Either {"Same Name.md", "Same Name (1).md"} or similar — must be 2 distinct.
        assert len(set(names)) == 2

    def test_atomic_notes_returns_zip(self, client, make_highlight, make_book):
        import io as _io, zipfile as _zip
        b = make_book(title="My Book", author="Alice", document_tags="philosophy")
        h1 = make_highlight(text="An idea worth pondering", note="why this matters", book=b, location=42)
        h2 = make_highlight(text="another quote", book=b, is_favorited=True)

        resp = client.get("/export/atomic-notes.zip")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/zip"
        zf = _zip.ZipFile(_io.BytesIO(resp.content))
        names = zf.namelist()
        # One file per highlight, named hl-{id}-{slug}.md
        assert len(names) == 2
        assert any(n.startswith(f"hl-{h1.id}-") and n.endswith(".md") for n in names)
        assert any(n.startswith(f"hl-{h2.id}-") and n.endswith(".md") for n in names)

        # Inspect h1's note: frontmatter + blockquote + Note section + backlink
        h1_name = next(n for n in names if n.startswith(f"hl-{h1.id}-"))
        body = zf.read(h1_name).decode("utf-8")
        assert body.startswith("---")
        assert f"id: freewise-{h1.id}" in body
        assert 'book: "My Book"' in body
        assert 'author: "Alice"' in body
        assert "location: 42" in body
        assert "is_favorited: false" in body
        assert "> An idea worth pondering" in body
        assert "## Note" in body
        assert "why this matters" in body
        assert "[[My Book]]" in body
        # Book document_tags merged into the per-highlight tags.
        assert '"philosophy"' in body

        # h2 (favorited, no note) — flag flips, no Note section.
        h2_body = zf.read(next(n for n in names if n.startswith(f"hl-{h2.id}-"))).decode("utf-8")
        assert "is_favorited: true" in h2_body
        assert "## Note" not in h2_body

    def test_atomic_notes_includes_highlight_tags(self, client, db, make_highlight, make_book):
        """Per-highlight tags from HighlightTag must surface in frontmatter."""
        import io as _io, zipfile as _zip
        from app.models import Tag, HighlightTag
        b = make_book(title="B")
        h = make_highlight(text="tagged", book=b)
        for name in ("python", "favorite", "django"):  # 'favorite' is reserved → filtered
            t = Tag(name=name)
            db.add(t); db.commit(); db.refresh(t)
            db.add(HighlightTag(highlight_id=h.id, tag_id=t.id))
        db.commit()
        resp = client.get("/export/atomic-notes.zip")
        body = _zip.ZipFile(_io.BytesIO(resp.content)).read(
            next(n for n in _zip.ZipFile(_io.BytesIO(resp.content)).namelist() if n.startswith(f"hl-{h.id}-"))
        ).decode("utf-8")
        assert '"python"' in body
        assert '"django"' in body
        assert '"favorite"' not in body  # reserved-name filter applies

    def test_atomic_notes_excludes_discarded(self, client, make_highlight, make_book):
        import io as _io, zipfile as _zip
        b = make_book(title="B")
        make_highlight(text="alive", book=b)
        make_highlight(text="dead", book=b, is_discarded=True)
        resp = client.get("/export/atomic-notes.zip")
        names = _zip.ZipFile(_io.BytesIO(resp.content)).namelist()
        assert len(names) == 1

    def test_atomic_notes_filter_by_book(self, client, make_highlight, make_book):
        import io as _io, zipfile as _zip
        b1 = make_book(title="A")
        b2 = make_book(title="B")
        make_highlight(text="from a", book=b1)
        make_highlight(text="from b", book=b2)
        resp = client.get("/export/atomic-notes.zip", params={"book_id": b1.id})
        assert resp.status_code == 200
        names = _zip.ZipFile(_io.BytesIO(resp.content)).namelist()
        assert len(names) == 1
        body = _zip.ZipFile(_io.BytesIO(resp.content)).read(names[0]).decode("utf-8")
        assert "from a" in body

    def test_atomic_notes_400_when_empty(self, client):
        resp = client.get("/export/atomic-notes.zip")
        assert resp.status_code == 400

    # ── Notion-flavored markdown export ─────────────────────────────────

    def test_notion_export_returns_zip_without_yaml(self, client, make_highlight, make_book):
        """Notion variant must NOT emit YAML frontmatter (Notion would render it
        as plain text). Highlights become bullets."""
        import io as _io, zipfile as _zip
        b = make_book(title="N Book", author="Author A", document_tags="topic")
        make_highlight(text="quote one", note="my note", book=b, location=12)
        make_highlight(text="quote two", book=b, is_favorited=True)

        resp = client.get("/export/notion.zip")
        assert resp.status_code == 200
        zf = _zip.ZipFile(_io.BytesIO(resp.content))
        body = zf.read("N Book.md").decode("utf-8")
        # No YAML fence at the top.
        assert not body.startswith("---")
        # H1 with title + 💡 callout block with metadata.
        assert "# N Book" in body
        assert "💡" in body
        assert "Author A" in body
        # Highlights as bullets.
        assert "- quote one" in body
        assert "- quote two" in body
        # Note nested as a sub-bullet.
        assert "  - my note" in body
        # Tag rendered as inline #topic in callout.
        assert "#topic" in body

    def test_notion_export_excludes_discarded(self, client, make_highlight, make_book):
        import io as _io, zipfile as _zip
        b = make_book(title="B")
        make_highlight(text="alive", book=b)
        make_highlight(text="dead", book=b, is_discarded=True)
        resp = client.get("/export/notion.zip")
        body = _zip.ZipFile(_io.BytesIO(resp.content)).read("B.md").decode("utf-8")
        assert "alive" in body
        assert "dead" not in body

    def test_notion_export_400_when_empty(self, client):
        assert client.get("/export/notion.zip").status_code == 400

    # ── Per-book single-file download ───────────────────────────────────

    def test_per_book_md_default_obsidian(self, client, make_highlight, make_book):
        b = make_book(title="One Book", author="Author")
        make_highlight(text="just one quote", book=b)
        resp = client.get(f"/export/book/{b.id}.md")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        cd = resp.headers.get("content-disposition", "")
        assert "One Book.md" in cd
        body = resp.text
        # Obsidian flavor: YAML frontmatter present.
        assert body.startswith("---")
        assert "> just one quote" in body

    def test_per_book_md_notion_flavor(self, client, make_highlight, make_book):
        b = make_book(title="Notion Book")
        make_highlight(text="bullet me", book=b)
        resp = client.get(f"/export/book/{b.id}.md", params={"flavor": "notion"})
        assert resp.status_code == 200
        body = resp.text
        # Notion flavor: no frontmatter, bullets.
        assert not body.startswith("---")
        assert "- bullet me" in body

    def test_per_book_md_404(self, client):
        assert client.get("/export/book/999999.md").status_code == 404

    def test_per_book_md_excludes_discarded(self, client, make_highlight, make_book):
        b = make_book(title="X")
        make_highlight(text="kept", book=b)
        make_highlight(text="trashed", book=b, is_discarded=True)
        body = client.get(f"/export/book/{b.id}.md").text
        assert "kept" in body
        assert "trashed" not in body

    def test_per_book_md_unknown_flavor_400(self, client, make_book, make_highlight):
        b = make_book(title="X")
        make_highlight(text="x", book=b)
        resp = client.get(f"/export/book/{b.id}.md", params={"flavor": "logseq-xtra"})
        assert resp.status_code == 400

    def test_books_csv_returns_inventory(self, client, make_book, make_highlight):
        b1 = make_book(title="A Book", author="Author A", document_tags="topic")
        b2 = make_book(title="B Book", author="Author B")
        make_highlight(text="x", book=b1)
        make_highlight(text="y", book=b1, is_favorited=True)
        make_highlight(text="z", book=b2)

        resp = client.get("/export/books.csv")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/csv")
        reader = csv.DictReader(io.StringIO(resp.text))
        rows = list(reader)
        assert {r["title"] for r in rows} == {"A Book", "B Book"}
        # A Book has 2 highlights, 1 favorited.
        a_row = next(r for r in rows if r["title"] == "A Book")
        assert a_row["highlight_count"] == "2"
        assert a_row["favorited_count"] == "1"
        assert a_row["author"] == "Author A"
        assert a_row["document_tags"] == "topic"

    def test_books_csv_400_when_empty(self, client):
        resp = client.get("/export/books.csv")
        assert resp.status_code == 400

    def test_books_csv_excludes_discarded_from_count(self, client, make_book, make_highlight):
        b = make_book(title="X")
        make_highlight(text="a", book=b)
        make_highlight(text="b", book=b, is_discarded=True)
        resp = client.get("/export/books.csv")
        rows = list(csv.DictReader(io.StringIO(resp.text)))
        x = next(r for r in rows if r["title"] == "X")
        # Discarded should not be counted in highlight_count.
        assert x["highlight_count"] == "1"

    def test_per_book_md_unicode_title(self, client, make_book, make_highlight):
        """Japanese / non-ASCII book titles must NOT crash the response with
        UnicodeEncodeError on the Content-Disposition header (uvicorn's
        latin-1 default). RFC 5987 filename* form covers this."""
        b = make_book(title="日本語タイトル")
        make_highlight(text="hello world", book=b)
        resp = client.get(f"/export/book/{b.id}.md")
        assert resp.status_code == 200
        cd = resp.headers.get("content-disposition", "")
        # Modern clients use the UTF-8 form
        assert "filename*=UTF-8''" in cd
        # Latin-1 fallback must be present and ASCII-only
        assert "filename=" in cd
        # Body is correct
        assert "hello world" in resp.text

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


class TestMarkdownExportFilters:
    """GET /export/markdown.zip — filter params mirror /export/csv (U88).

    Each test verifies the resulting ZIP only contains .md files for books
    that have at least one matching highlight after filtering — empty books
    must NOT produce empty .md files.
    """

    @staticmethod
    def _open_zip(resp):
        import io as _io
        import zipfile as _zip
        return _zip.ZipFile(_io.BytesIO(resp.content))

    def test_filter_favorited_only(self, client, make_highlight, make_book):
        """favorited_only=true returns only books that have a favorited match."""
        b1 = make_book(title="FavBook")
        b2 = make_book(title="PlainBook")
        make_highlight(text="keep me", book=b1, is_favorited=True)
        make_highlight(text="not me", book=b2)

        resp = client.get("/export/markdown.zip?favorited_only=true")
        assert resp.status_code == 200
        zf = self._open_zip(resp)
        names = zf.namelist()
        # Only the favorited book's .md should be in the archive.
        assert any("FavBook" in n for n in names)
        assert not any("PlainBook" in n for n in names)
        body = zf.read(next(n for n in names if "FavBook" in n)).decode("utf-8")
        assert "keep me" in body
        assert "not me" not in body
        assert "highlight_count: 1" in body

    def test_filter_book_id(self, client, make_highlight, make_book):
        """book_id scopes the export to a single book."""
        b1 = make_book(title="One")
        b2 = make_book(title="Two")
        make_highlight(text="from one", book=b1)
        make_highlight(text="from two", book=b2)

        resp = client.get(f"/export/markdown.zip?book_id={b1.id}")
        assert resp.status_code == 200
        names = self._open_zip(resp).namelist()
        assert any("One" in n for n in names)
        assert not any(n == "Two.md" for n in names)
        # Only one .md emitted because only one book matches.
        assert len(names) == 1

    def test_filter_author(self, client, make_highlight, make_book):
        """author exact-match filters by Book.author."""
        a = make_book(title="A1", author="Alice")
        b = make_book(title="B1", author="Bob")
        make_highlight(text="alice quote", book=a)
        make_highlight(text="bob quote", book=b)

        resp = client.get("/export/markdown.zip?author=Alice")
        assert resp.status_code == 200
        names = self._open_zip(resp).namelist()
        assert any("A1" in n for n in names)
        assert not any("B1" in n for n in names)
        assert len(names) == 1

    def test_filter_tag(self, client, db, make_highlight, make_book):
        """tag filter narrows highlights, dropping books without a match."""
        from app.models import Tag, HighlightTag
        b1 = make_book(title="Tagged")
        b2 = make_book(title="Untagged")
        h1 = make_highlight(text="ml stuff", book=b1)
        make_highlight(text="other stuff", book=b2)
        t = Tag(name="ml"); db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h1.id, tag_id=t.id))
        db.commit()

        resp = client.get("/export/markdown.zip?tag=ml")
        assert resp.status_code == 200
        zf = self._open_zip(resp)
        names = zf.namelist()
        assert any("Tagged" in n and "Untagged" not in n for n in names)
        assert not any("Untagged" in n for n in names)
        body = zf.read(next(n for n in names if "Tagged" in n)).decode("utf-8")
        assert "ml stuff" in body
        assert "other stuff" not in body

    def test_filter_no_match_returns_400(self, client, make_highlight):
        """When all filters narrow to zero rows, return the U88 message."""
        make_highlight(text="nothing favorited")

        resp = client.get("/export/markdown.zip?favorited_only=true")
        assert resp.status_code == 400
        # Same message shape as /export/csv's filter-narrowed-to-zero branch.
        assert "filters" in resp.text.lower()
        assert "No highlights match the supplied filters" in resp.text

    def test_filters_compose(self, client, db, make_highlight, make_book):
        """tag + favorited_only must AND, not OR — and only the matching
        book gets a .md file."""
        from app.models import Tag, HighlightTag
        b1 = make_book(title="Match")
        b2 = make_book(title="OtherBook")
        h_fav_tagged = make_highlight(text="fav+tag", book=b1, is_favorited=True)
        make_highlight(text="fav only", book=b1, is_favorited=True)
        h_tag_only = make_highlight(text="tag only", book=b2)
        t = Tag(name="ml"); db.add(t); db.commit(); db.refresh(t)
        db.add(HighlightTag(highlight_id=h_fav_tagged.id, tag_id=t.id))
        db.add(HighlightTag(highlight_id=h_tag_only.id, tag_id=t.id))
        db.commit()

        resp = client.get("/export/markdown.zip?tag=ml&favorited_only=true")
        assert resp.status_code == 200
        zf = self._open_zip(resp)
        names = zf.namelist()
        # Only the book with a fav+tag highlight should produce a file.
        assert any("Match" in n for n in names)
        assert not any("OtherBook" in n for n in names)
        assert len(names) == 1
        body = zf.read(next(n for n in names if "Match" in n)).decode("utf-8")
        assert "fav+tag" in body
        # The fav-only and tag-only highlights are filtered out.
        assert "fav only" not in body
        assert "tag only" not in body
        assert "highlight_count: 1" in body
