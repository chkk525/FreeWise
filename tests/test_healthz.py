"""Tests for the /healthz monitoring probe."""

from __future__ import annotations


def test_healthz_returns_ok_with_counts(client, make_highlight):
    make_highlight(text="x")
    make_highlight(text="y", is_discarded=True)
    resp = client.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["highlights"]["active"] == 1   # discarded excluded
    assert body["highlights"]["embedded"] == 0
    assert body["highlights"]["embedded_pct"] == 0.0
    assert "embed_model" in body
    # Ollama reachability is best-effort; field always present.
    assert "ollama" in body
    assert "reachable" in body["ollama"]


def test_healthz_reports_embedded_pct(client, db, make_highlight):
    from app.models import Embedding
    from app.services.embeddings import _env_model, pack_vector

    h1 = make_highlight(text="a")
    make_highlight(text="b")
    db.add(Embedding(
        highlight_id=h1.id, model_name=_env_model(), dim=1,
        vector=pack_vector([1.0]),
    ))
    db.commit()
    resp = client.get("/healthz")
    body = resp.json()
    assert body["highlights"]["embedded"] == 1
    assert body["highlights"]["embedded_pct"] == 50.0


def test_healthz_no_auth_required(client):
    """Public probe — no Authorization header needed."""
    assert client.get("/healthz").status_code == 200


def test_healthz_ollama_reachable_field_always_present(client):
    """Whether or not Ollama is up, the probe shouldn't 5xx."""
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert isinstance(resp.json()["ollama"]["reachable"], bool)
