"""Tests for GET /api/v2/admin/backup — atomic SQLite snapshot endpoint."""

from __future__ import annotations

import hashlib
import sqlite3

from app.models import ApiToken, Highlight


def _seed_token(db, value: str = "good-token", user_id: int = 1) -> ApiToken:
    token = ApiToken(
        token_prefix=value[:16],
        token_hash=hashlib.sha256(value.encode("utf-8")).hexdigest(),
        name="backup-test",
        user_id=user_id,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return token


def test_backup_requires_auth(client):
    resp = client.get("/api/v2/admin/backup")
    assert resp.status_code == 401


def test_backup_streams_sqlite_snapshot(client, db, tmp_path, make_highlight):
    _seed_token(db, "good-token")
    h = make_highlight(text="content that should appear in the backup")

    resp = client.get(
        "/api/v2/admin/backup",
        headers={"Authorization": "Token good-token"},
    )
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/x-sqlite3"
    cd = resp.headers["content-disposition"]
    assert "freewise-" in cd and ".sqlite" in cd

    out = tmp_path / "snapshot.sqlite"
    out.write_bytes(resp.content)

    # SQLite header magic confirms this is a real DB, not just bytes.
    assert out.read_bytes()[:16] == b"SQLite format 3\x00"

    # Open the snapshot and verify our seeded highlight made it through.
    conn = sqlite3.connect(str(out))
    try:
        cur = conn.execute("SELECT text FROM highlight WHERE id = ?", (h.id,))
        row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "content that should appear in the backup"


def test_backup_service_unit(tmp_path, db):
    """Service-level smoke test against a fresh file engine."""
    from sqlmodel import SQLModel, create_engine

    src = tmp_path / "src.sqlite"
    engine = create_engine(f"sqlite:///{src}")
    SQLModel.metadata.create_all(engine)

    from app.services.backup import make_backup_to_path

    out = tmp_path / "out.sqlite"
    written = make_backup_to_path(engine, str(out))
    assert written > 0
    assert out.read_bytes()[:16] == b"SQLite format 3\x00"


def test_backup_rate_limit_caps_at_three_per_minute(client, db):
    """Backup is amplification-heavy; per-path bucket should kick in at 3/min."""
    _seed_token(db, "good-token")
    headers = {"Authorization": "Token good-token"}
    # First 3 should pass (under MAX_HITS_BACKUP=3).
    for _ in range(3):
        r = client.get("/api/v2/admin/backup", headers=headers)
        assert r.status_code == 200
    # 4th hits the per-path cap → 429 with Retry-After.
    r = client.get("/api/v2/admin/backup", headers=headers)
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_backup_service_rejects_non_sqlite():
    """Non-sqlite engines should fail fast rather than silently corrupting."""
    from unittest.mock import MagicMock

    from app.services.backup import make_backup_to_path

    engine = MagicMock()
    engine.dialect.name = "postgresql"

    try:
        make_backup_to_path(engine, "/tmp/should-not-write.sqlite")
    except RuntimeError as e:
        assert "sqlite" in str(e).lower()
    else:
        raise AssertionError("expected RuntimeError for non-sqlite engine")
