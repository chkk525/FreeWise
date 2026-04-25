"""
Integration tests for the Kindle JSON import HTTP routes.
"""
import io
import json
from pathlib import Path

from sqlmodel import select

from app.models import Book, Highlight


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "kindle_notebook_sample.json"


class TestKindleImportPage:
    def test_page_loads(self, client):
        resp = client.get("/import/ui/kindle")
        assert resp.status_code == 200
        assert "Kindle" in resp.text

    def test_import_main_template_includes_kindle_card(self):
        """Verify the import-source picker template links to the Kindle import page.

        Asserted at the template-source level rather than via /import/ui because
        that legacy route currently fails on starlette 1.0 (pre-existing issue,
        unrelated to this importer). See commit message.
        """
        template_path = (
            Path(__file__).resolve().parent.parent
            / "app"
            / "templates"
            / "import_main.html"
        )
        body = template_path.read_text(encoding="utf-8")
        assert "/import/ui/kindle" in body
        assert "Kindle" in body


class TestKindleImportUpload:
    def _upload(self, client, payload_bytes: bytes, filename: str = "kindle.json"):
        buf = io.BytesIO(payload_bytes)
        return client.post(
            "/import/ui/kindle",
            files={"file": (filename, buf, "application/json")},
        )

    def test_basic_import(self, client, db):
        resp = self._upload(client, FIXTURE_PATH.read_bytes())
        assert resp.status_code == 200
        assert "Imported" in resp.text or "Import Complete" in resp.text

        books = db.exec(select(Book)).all()
        assert len(books) == 2
        highlights = db.exec(select(Highlight)).all()
        assert len(highlights) == 4

    def test_reject_non_json_filename(self, client):
        resp = client.post(
            "/import/ui/kindle",
            files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
        )
        assert resp.status_code == 400

    def test_reject_unsupported_schema(self, client, db):
        payload = json.dumps(
            {
                "schema_version": "99.0",
                "exported_at": "2026-04-25T00:00:00Z",
                "source": "kindle_notebook",
                "books": [],
            }
        ).encode("utf-8")
        resp = self._upload(client, payload)
        # Renders error page (status 400) — the importer raises ValueError.
        assert resp.status_code == 400
        assert "schema_version" in resp.text.lower() or "import failed" in resp.text.lower()
