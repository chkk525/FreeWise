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
               include_discarded: bool = False) -> dict:
        return self._request(
            "GET",
            "/api/v2/highlights/search",
            params={
                "q": q, "page": page, "page_size": page_size,
                "include_discarded": str(include_discarded).lower(),
            },
        )

    def list_highlights(self, *, page: int = 1, page_size: int = 50,
                        book_id: int | None = None) -> dict:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if book_id is not None:
            params["book_id"] = book_id
        return self._request("GET", "/api/v2/highlights/", params=params)

    def get_highlight(self, highlight_id: int) -> dict:
        return self._request("GET", f"/api/v2/highlights/{highlight_id}")

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

    def stats(self) -> dict:
        return self._request("GET", "/api/v2/stats")

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
