"""Thin HTTP wrapper around the FreeWise /api/v2 endpoints used by the CLI.

The wrapper is transport-agnostic: in production it spawns an ``httpx.Client``
against a real socket. Tests inject a Starlette ``TestClient`` (which has the
same ``.request()`` shape) so the CLI can be exercised end-to-end against the
FastAPI app in-process — no socket, no ASGI/async dance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import httpx


class FreewiseError(Exception):
    """Raised when the server returns a non-2xx response."""

    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status = status
        self.body = body


class _SyncHttpClient(Protocol):
    """Minimal interface satisfied by both httpx.Client and Starlette TestClient."""

    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


@dataclass
class Client:
    url: str
    token: str | None
    # Optional injectable HTTP client. Production callers leave this None and
    # we open an httpx.Client per request; tests pass a Starlette TestClient.
    http: _SyncHttpClient | None = None

    def _headers(self) -> dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": "freewise-cli/0.1"}
        if self.token:
            # FreeWise's /api/v2 follows Readwise's convention: ``Token <value>``,
            # not ``Bearer <value>``. See app/api_v2/auth.py.
            h["Authorization"] = f"Token {self.token}"
        return h

    def _request(self, method: str, path: str, **kw: Any) -> Any:
        if self.http is not None:
            # Tests: TestClient accepts paths starting with /, no host needed.
            r = self.http.request(method, path, headers=self._headers(), **kw)
        else:
            full = f"{self.url.rstrip('/')}{path}"
            with httpx.Client(timeout=30.0) as c:
                r = c.request(method, full, headers=self._headers(), **kw)
        if r.status_code == 204:
            return None
        if r.status_code >= 400:
            raise FreewiseError(r.status_code, r.text)
        ct = r.headers.get("content-type", "")
        if "application/json" in ct:
            return r.json()
        return r.text

    # Convenience wrappers per endpoint --------------------------------------

    def auth_check(self) -> None:
        self._request("GET", "/api/v2/auth/")

    def search(self, q: str, *, page: int = 1, page_size: int = 50,
               include_discarded: bool = False, tag: str | None = None) -> dict:
        params: dict[str, Any] = {
            "q": q, "page": page, "page_size": page_size,
            "include_discarded": str(include_discarded).lower(),
        }
        if tag:
            params["tag"] = tag
        return self._request("GET", "/api/v2/highlights/search", params=params)

    def list_highlights(self, *, page: int = 1, page_size: int = 50,
                        book_id: int | None = None) -> dict:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if book_id is not None:
            params["book_id"] = book_id
        return self._request("GET", "/api/v2/highlights/", params=params)

    def get_highlight(self, highlight_id: int) -> dict:
        return self._request("GET", f"/api/v2/highlights/{highlight_id}")

    def ask(self, question: str, *, top_k: int = 8,
            embed_model: str | None = None,
            generate_model: str | None = None) -> dict:
        body: dict[str, Any] = {"question": question, "top_k": top_k}
        if embed_model:
            body["embed_model"] = embed_model
        if generate_model:
            body["generate_model"] = generate_model
        return self._request("POST", "/api/v2/ask", json=body)

    def backfill_embeddings(self, *, batch_size: int = 64,
                            model: str | None = None) -> dict:
        """Run one batch of the embedding backfill on the server side."""
        body: dict[str, Any] = {"batch_size": batch_size}
        if model:
            body["model"] = model
        return self._request("POST", "/api/v2/embeddings/backfill", json=body)

    def related_highlights(self, highlight_id: int, *, limit: int = 10,
                           model: str | None = None) -> dict:
        params: dict[str, Any] = {"limit": limit}
        if model:
            params["model"] = model
        return self._request(
            "GET", f"/api/v2/highlights/{highlight_id}/related", params=params,
        )

    def random_highlight(self, *, include_discarded: bool = False,
                         include_mastered: bool = True,
                         book_id: int | None = None) -> dict:
        params: dict[str, Any] = {
            "include_discarded": str(include_discarded).lower(),
            "include_mastered": str(include_mastered).lower(),
        }
        if book_id is not None:
            params["book_id"] = book_id
        return self._request("GET", "/api/v2/highlights/random", params=params)

    def patch_highlight(self, highlight_id: int, **fields: Any) -> dict:
        return self._request(
            "PATCH",
            f"/api/v2/highlights/{highlight_id}",
            json={k: v for k, v in fields.items() if v is not None},
        )

    def list_books(self, *, page: int = 1, page_size: int = 50) -> dict:
        return self._request(
            "GET", "/api/v2/books/", params={"page": page, "page_size": page_size},
        )

    def list_authors(self, *, page: int = 1, page_size: int = 50,
                     q: str | None = None) -> dict:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if q:
            params["q"] = q
        return self._request("GET", "/api/v2/authors", params=params)

    def list_tag_summary(self, *, page: int = 1, page_size: int = 100,
                         q: str | None = None) -> dict:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if q:
            params["q"] = q
        return self._request("GET", "/api/v2/tags", params=params)

    def stats(self) -> dict:
        return self._request("GET", "/api/v2/stats")

    def list_tags(self, highlight_id: int) -> dict:
        return self._request("GET", f"/api/v2/highlights/{highlight_id}/tags")

    def add_tag(self, highlight_id: int, name: str) -> dict:
        return self._request(
            "POST", f"/api/v2/highlights/{highlight_id}/tags",
            json={"name": name},
        )

    def remove_tag(self, highlight_id: int, name: str) -> dict:
        from urllib.parse import quote
        # Encode the tag in the path so spaces / non-ASCII round-trip safely.
        return self._request(
            "DELETE", f"/api/v2/highlights/{highlight_id}/tags/{quote(name, safe='')}",
        )

    def stream_export(self, fmt: str, *, book_id: int | None = None) -> tuple[bytes, str | None]:
        """Fetch /export/<fmt> and return (bytes, suggested filename).

        Streams when possible — uses httpx.stream in production. With an
        injected sync HTTP client (TestClient) we just call request() since
        TestClient already buffers the response into memory.
        """
        if fmt == "csv":
            path = "/export/csv"
        elif fmt in ("md", "markdown"):
            path = "/export/markdown.zip"
        elif fmt in ("atomic", "atomic-notes"):
            path = "/export/atomic-notes.zip"
            if book_id is not None:
                path = f"{path}?book_id={book_id}"
        else:
            raise ValueError(f"Unknown export format: {fmt!r}")

        if self.http is not None:
            r = self.http.request("GET", path, headers=self._headers())
            if r.status_code >= 400:
                raise FreewiseError(r.status_code, r.text)
            cd = r.headers.get("content-disposition", "")
            return r.content, _filename_from_cd(cd)

        full = f"{self.url.rstrip('/')}{path}"
        with httpx.Client(timeout=120.0) as c:
            r = c.get(full, headers=self._headers())
        if r.status_code >= 400:
            raise FreewiseError(r.status_code, r.text)
        return r.content, _filename_from_cd(r.headers.get("content-disposition", ""))

    def create_highlight(self, *, text: str, title: str | None = None,
                         author: str | None = None, note: str | None = None,
                         location: int | None = None,
                         location_type: str | None = None) -> dict:
        item: dict[str, Any] = {"text": text}
        if title: item["title"] = title
        if author: item["author"] = author
        if note: item["note"] = note
        if location is not None: item["location"] = location
        if location_type: item["location_type"] = location_type
        return self._request(
            "POST", "/api/v2/highlights/", json={"highlights": [item]},
        )


def _filename_from_cd(cd: str) -> str | None:
    """Pull the filename out of a Content-Disposition header. Best-effort."""
    if not cd:
        return None
    import re
    m = re.search(r'filename="([^"]+)"', cd)
    return m.group(1) if m else None
