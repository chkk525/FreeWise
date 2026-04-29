"""Tests for ApiToken.scopes column + require_scope dependency."""
from __future__ import annotations

import json

from app.models import ApiToken


def _envelope():
    return {
        "schema_version": "1.0",
        "exported_at": "2026-04-29T00:00:00Z",
        "source": "kindle_notebook",
        "books": [],
    }


def _seed_token(db, *, value: str, scopes: str | None) -> ApiToken:
    t = ApiToken(token=value, name=f"scoped-{value}", user_id=1, scopes=scopes)
    db.add(t)
    db.commit()
    return t


def test_token_with_kindle_import_scope_passes(client, db):
    _seed_token(db, value="tok-kindle", scopes="kindle:import")
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token tok-kindle"},
    )
    # Empty `books` list is valid per schema; result is 200 with zero counts.
    assert r.status_code == 200, r.text


def test_token_without_kindle_import_scope_returns_403(client, db):
    _seed_token(db, value="tok-readonly", scopes="highlights:read")
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token tok-readonly"},
    )
    assert r.status_code == 403
    assert "kindle:import" in r.json()["detail"]


def test_token_with_no_scopes_acts_as_full_access_legacy(client, db):
    """Backwards-compat: pre-scopes tokens (scopes IS NULL) keep full access."""
    _seed_token(db, value="tok-legacy", scopes=None)
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token tok-legacy"},
    )
    assert r.status_code == 200, r.text


def test_token_with_multiple_scopes_passes_when_any_match(client, db):
    _seed_token(
        db,
        value="tok-multi",
        scopes="highlights:read,kindle:import,books:read",
    )
    r = client.post(
        "/api/v2/imports/kindle",
        json=_envelope(),
        headers={"Authorization": "Token tok-multi"},
    )
    assert r.status_code == 200, r.text
