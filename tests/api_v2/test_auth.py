"""Integration tests for the v2 API bearer-token authentication."""

from __future__ import annotations

import hashlib

from app.models import ApiToken


def _seed_token(db, value: str = "good-token", user_id: int = 1) -> ApiToken:
    """Insert a HASHED token (Phase 4 storage shape) and return the row."""
    token = ApiToken(
        token_prefix=value[:16],
        token_hash=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        name="test-token",
        user_id=user_id,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def _seed_legacy_token(db, value: str = "legacy-token", user_id: int = 1) -> ApiToken:
    """Insert a PLAINTEXT token (pre-Phase-4 storage) for the legacy fallback path."""
    token = ApiToken(token=value, name="legacy", user_id=user_id)
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def test_auth_success_returns_204(client, db):
    _seed_token(db, "good-token")
    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token good-token"}
    )
    assert resp.status_code == 204
    assert resp.text == ""


def test_auth_missing_header_returns_401(client):
    resp = client.get("/api/v2/auth/")
    assert resp.status_code == 401


def test_auth_wrong_scheme_returns_401(client, db):
    """Readwise uses ``Token``, not ``Bearer`` — anything else must be rejected."""
    _seed_token(db, "good-token")
    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Bearer good-token"}
    )
    assert resp.status_code == 401


def test_auth_unknown_token_returns_401(client, db):
    _seed_token(db, "good-token")
    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token unknown"}
    )
    assert resp.status_code == 401


def test_auth_empty_token_returns_401(client):
    resp = client.get("/api/v2/auth/", headers={"Authorization": "Token "})
    assert resp.status_code == 401


def test_auth_updates_last_used_at(client, db):
    """The first authenticated call must populate last_used_at; subsequent
    calls within the debounce window may skip the write."""
    # Use a unique token so the per-token debounce cache doesn't suppress us.
    token = _seed_token(db, "fresh-token-for-touch-test")
    assert token.last_used_at is None

    # Reset the per-token debounce cache so this test isn't ordering-sensitive.
    from app.api_v2 import auth as auth_module
    auth_module._last_used_at_cache.clear()

    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token fresh-token-for-touch-test"}
    )
    assert resp.status_code == 204

    db.expire_all()
    refreshed = db.get(ApiToken, token.id)
    assert refreshed.last_used_at is not None


def test_auth_legacy_plaintext_token_works_and_gets_upgraded(client, db):
    """A pre-migration row stored as plaintext must still authenticate, and
    the row should be hashed in place after the first hit."""
    token = _seed_legacy_token(db, "legacy-plaintext-value")
    assert token.token_hash is None
    assert token.token == "legacy-plaintext-value"

    from app.api_v2 import auth as auth_module
    auth_module._last_used_at_cache.clear()

    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token legacy-plaintext-value"}
    )
    assert resp.status_code == 204

    db.expire_all()
    refreshed = db.get(ApiToken, token.id)
    assert refreshed.token is None  # plaintext cleared
    assert refreshed.token_hash == hashlib.sha256(
        b"legacy-plaintext-value"
    ).hexdigest()


def test_auth_debounce_suppresses_repeat_writes(client, db):
    """A second auth call within the debounce window must not re-commit."""
    token = _seed_token(db, "debounce-token")

    from app.api_v2 import auth as auth_module
    auth_module._last_used_at_cache.clear()

    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token debounce-token"}
    )
    assert resp.status_code == 204

    db.expire_all()
    first_touch = db.get(ApiToken, token.id).last_used_at
    assert first_touch is not None

    # Second call: should be debounced — last_used_at unchanged.
    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token debounce-token"}
    )
    assert resp.status_code == 204
    db.expire_all()
    second_touch = db.get(ApiToken, token.id).last_used_at
    assert second_touch == first_touch  # still the first value


# ── Rate limit + security headers ───────────────────────────────────────────


def test_security_headers_present(client):
    """Every response should carry the defence-in-depth headers."""
    resp = client.get("/api/v2/auth/", headers={"Authorization": "Token nope"})
    assert resp.headers.get("x-content-type-options") == "nosniff"
    assert resp.headers.get("x-frame-options") == "DENY"
    assert "default-src 'self'" in (resp.headers.get("content-security-policy") or "")


def test_rate_limit_429_after_burst(client):
    """61 unauthenticated calls within the window should yield at least one 429."""
    # Reset the bucket so this test isn't ordering-sensitive.
    from app.main import _RATE_LIMIT_BUCKET
    _RATE_LIMIT_BUCKET.clear()

    seen_429 = False
    for _ in range(70):
        r = client.get("/api/v2/auth/", headers={"Authorization": "Token x"})
        if r.status_code == 429:
            seen_429 = True
            assert int(r.headers.get("retry-after", "0")) >= 1
            break
    assert seen_429, "expected at least one 429 inside 70 calls/window"
