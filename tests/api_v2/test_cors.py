"""CORS preflight + headers for chrome-extension origin."""
from __future__ import annotations


def test_options_preflight_from_extension_origin_succeeds(client):
    r = client.options(
        "/api/v2/imports/kindle",
        headers={
            "Origin": "chrome-extension://abcdef1234567890abcdef1234567890",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "authorization,content-type,content-encoding",
        },
    )
    assert r.status_code == 200
    assert "POST" in r.headers.get("access-control-allow-methods", "")
    headers = r.headers.get("access-control-allow-headers", "").lower()
    assert "authorization" in headers


def test_post_from_extension_origin_includes_cors_headers(client, valid_token):
    """The actual POST must echo the origin so the browser accepts the response."""
    r = client.post(
        "/api/v2/imports/kindle",
        json={
            "schema_version": "1.0",
            "exported_at": "2026-04-29T00:00:00Z",
            "source": "kindle_notebook",
            "books": [],
        },
        headers={
            "Authorization": f"Token {valid_token}",
            "Origin": "chrome-extension://abcdef1234567890abcdef1234567890",
        },
    )
    assert r.status_code == 200
    origin_echo = r.headers.get("access-control-allow-origin", "")
    assert origin_echo.startswith("chrome-extension://")


def test_post_from_disallowed_origin_no_cors_header(client, valid_token):
    r = client.post(
        "/api/v2/imports/kindle",
        json={
            "schema_version": "1.0",
            "exported_at": "2026-04-29T00:00:00Z",
            "source": "kindle_notebook",
            "books": [],
        },
        headers={
            "Authorization": f"Token {valid_token}",
            "Origin": "https://evil.example.com",
        },
    )
    assert r.status_code == 200  # the request itself succeeds — CORS is a browser-side enforcement
    # But there must be NO Access-Control-Allow-Origin header echoing evil.example.com
    assert "evil.example.com" not in r.headers.get("access-control-allow-origin", "")
