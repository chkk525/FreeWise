"""Integration tests for the v2 API bearer-token authentication."""

from __future__ import annotations

from app.models import ApiToken


def _seed_token(db, value: str = "good-token", user_id: int = 1) -> ApiToken:
    token = ApiToken(token=value, name="test-token", user_id=user_id)
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
    token = _seed_token(db, "good-token")
    assert token.last_used_at is None

    resp = client.get(
        "/api/v2/auth/", headers={"Authorization": "Token good-token"}
    )
    assert resp.status_code == 204

    db.expire_all()
    refreshed = db.get(ApiToken, token.id)
    assert refreshed.last_used_at is not None
