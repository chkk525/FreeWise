"""Branded HTML error pages for typo'd URLs.

The FastAPI default of `{"detail":"Not Found"}` looks like the site
crashed when a user clicks a stale link from a bookmark. We render a
nav-bearing HTML page for browser requests but keep JSON for API /
CLI / extension clients.
"""
from __future__ import annotations


class TestBrandedErrorPages:
    """`@app.exception_handler(StarletteHTTPException)` and 500."""

    def test_404_renders_html_for_browser_navigation(self, client):
        resp = client.get(
            "/this-route-does-not-exist",
            headers={"Accept": "text/html"},
        )
        assert resp.status_code == 404
        assert "text/html" in resp.headers["content-type"]
        # Branded page includes the FreeWise nav.
        assert "Dashboard" in resp.text
        assert "Page not found" in resp.text

    def test_404_returns_json_for_api_clients(self, client):
        # No `Accept: text/html` header — programmatic client.
        resp = client.get("/this-route-does-not-exist")
        assert resp.status_code == 404
        assert "application/json" in resp.headers["content-type"]
        assert resp.json() == {"detail": "Not Found"}

    def test_404_renders_html_for_htmx(self, client):
        # HTMX swaps go into HTML slots, so the partial slot should also
        # get an HTML response (not raw JSON crashing the swap).
        resp = client.get(
            "/this-route-does-not-exist",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 404
        assert "text/html" in resp.headers["content-type"]

    def test_api_v2_404_stays_json(self, client):
        # API surface keeps machine-readable JSON regardless of Accept,
        # since CLI / extension / MCP all consume it.
        resp = client.get(
            "/api/v2/highlights/9999999999",
            headers={"Accept": "text/html"},
        )
        # Token-protected route — surface depends on auth, but the
        # response shape must be JSON either way.
        assert resp.status_code in (401, 404)
        assert "application/json" in resp.headers["content-type"]

    def test_existing_pages_still_200(self, client):
        # Sanity: the new exception handler must not shadow successful
        # routes.
        resp = client.get("/dashboard/ui")
        assert resp.status_code == 200
        assert "Dashboard" in resp.text
