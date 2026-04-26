"""C2 round 1 — substrate tests for the embedding model + Ollama service.

We don't need a running Ollama instance: the OllamaClient takes an
injectable ``http`` (httpx.Client) and we wrap it in a ``MockTransport``
that returns canned JSON. This exercises the full request/response
serialization path without any network I/O.
"""

from __future__ import annotations

import json
import struct

import httpx
import pytest

from app.models import Embedding, Highlight
from app.services.embeddings import (
    OllamaClient,
    OllamaUnavailable,
    cosine_similarity,
    pack_vector,
    unpack_vector,
)


# ── Vector serialization ──────────────────────────────────────────────────


def test_pack_unpack_roundtrip():
    vec = [0.1, -0.2, 0.3, 1.0, -1.5]
    blob = pack_vector(vec)
    assert isinstance(blob, bytes)
    assert len(blob) == 5 * 4  # 4 bytes per float32
    out = unpack_vector(blob, dim=5)
    # float32 precision means we don't get bit-exact, but very close.
    for a, b in zip(vec, out):
        assert abs(a - b) < 1e-6


def test_unpack_dim_mismatch_raises():
    blob = pack_vector([1.0, 2.0, 3.0])
    with pytest.raises(ValueError):
        unpack_vector(blob, dim=99)


def test_cosine_basic_cases():
    # Identical → 1.0
    assert abs(cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-9
    # Orthogonal → 0.0
    assert abs(cosine_similarity([1, 0], [0, 1])) < 1e-9
    # Opposite → -1.0
    assert abs(cosine_similarity([1, 0], [-1, 0]) - (-1.0)) < 1e-9
    # Zero vector → 0.0 (defensively, no DivisionByZero)
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0


def test_cosine_dim_mismatch_raises():
    with pytest.raises(ValueError):
        cosine_similarity([1, 2], [1, 2, 3])


# ── OllamaClient with mocked transport ────────────────────────────────────


def _make_mock_client(handler) -> httpx.Client:
    """Wrap a request handler in a synchronous httpx Client."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embed_one_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/embeddings"
        body = json.loads(request.content)
        assert body["model"] == "test-model"
        assert body["prompt"] == "hello world"
        return httpx.Response(200, json={"embedding": [0.1, 0.2, 0.3]})

    client = OllamaClient(
        base_url="http://fake", model="test-model", http=_make_mock_client(handler),
    )
    vec = client.embed_one("hello world")
    assert vec == pytest.approx([0.1, 0.2, 0.3])


def test_embed_batch_keeps_order():
    seen_prompts: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen_prompts.append(body["prompt"])
        # Return a vector that encodes the prompt length so we can verify
        # the per-prompt round-trip.
        return httpx.Response(200, json={"embedding": [float(len(body["prompt"]))]})

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    out = client.embed_batch(["a", "bbb", "cc"])
    assert seen_prompts == ["a", "bbb", "cc"]
    assert out == [[1.0], [3.0], [2.0]]


def test_embed_batch_empty_string_returns_empty_vector():
    """Empty texts should NOT hit the network; output stays index-aligned."""
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"embedding": [1.0]})

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    out = client.embed_batch(["x", "", "y"])
    assert calls == 2  # only "x" and "y" hit the wire
    assert out == [[1.0], [], [1.0]]


def test_embed_raises_ollama_unavailable_on_4xx():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="model not found")

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    with pytest.raises(OllamaUnavailable) as ei:
        client.embed_one("x")
    assert "404" in str(ei.value)


def test_embed_raises_ollama_unavailable_on_garbage_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    with pytest.raises(OllamaUnavailable):
        client.embed_one("x")


def test_embed_raises_ollama_unavailable_when_embedding_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unrelated": "field"})

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    with pytest.raises(OllamaUnavailable):
        client.embed_one("x")


def test_embed_raises_ollama_unavailable_on_connection_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    client = OllamaClient(
        base_url="http://fake", model="test", http=_make_mock_client(handler),
    )
    with pytest.raises(OllamaUnavailable) as ei:
        client.embed_one("x")
    assert "could not reach Ollama" in str(ei.value)


# ── Embedding model integration with the existing schema ─────────────────


def test_embedding_table_created(db, make_highlight):
    """The migration should have created the table and we should be able
    to write/read a row through SQLModel against the live test engine."""
    h = make_highlight(text="emb me")
    blob = pack_vector([0.1, 0.2, 0.3])
    e = Embedding(
        highlight_id=h.id, model_name="test-model", dim=3, vector=blob,
    )
    db.add(e); db.commit(); db.refresh(e)
    assert e.id is not None
    assert e.dim == 3

    # Round-trip the vector.
    fetched = db.get(Embedding, e.id)
    assert fetched is not None
    assert unpack_vector(fetched.vector, fetched.dim) == pytest.approx([0.1, 0.2, 0.3])


def test_embedding_unique_per_highlight_model(db, make_highlight):
    """The (highlight_id, model_name) unique index should reject duplicates."""
    from sqlalchemy.exc import IntegrityError

    h = make_highlight(text="x")
    blob = pack_vector([1.0])
    db.add(Embedding(highlight_id=h.id, model_name="m1", dim=1, vector=blob))
    db.commit()
    # Same (highlight, model) should fail.
    db.add(Embedding(highlight_id=h.id, model_name="m1", dim=1, vector=blob))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    # Different model is fine.
    db.add(Embedding(highlight_id=h.id, model_name="m2", dim=1, vector=blob))
    db.commit()
