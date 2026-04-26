"""Ollama-backed embedding service (C2 round 1).

Why Ollama:
- Self-hosted aligns with FreeWise's privacy ethos.
- Zero new heavy Python deps — just an HTTP call via httpx (already used).
- Easy model swap via env var; no PyTorch, no ONNX runtime.
- Optional: if Ollama isn't reachable, the rest of the app keeps working;
  related-highlight features simply degrade.

Configuration (env vars):
- ``FREEWISE_OLLAMA_URL``   default ``http://localhost:11434``
- ``FREEWISE_OLLAMA_EMBED_MODEL`` default ``nomic-embed-text``

This module knows nothing about the database. The forthcoming backfill
job in round 2 reads highlights, calls ``embed_texts``, and writes rows
to the ``embedding`` table.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import Iterable

import httpx


# ── Configuration ──────────────────────────────────────────────────────────


def _env_url() -> str:
    return os.environ.get("FREEWISE_OLLAMA_URL", "http://localhost:11434").rstrip("/")


def _env_model() -> str:
    return os.environ.get("FREEWISE_OLLAMA_EMBED_MODEL", "nomic-embed-text")


# ── Errors ─────────────────────────────────────────────────────────────────


class OllamaUnavailable(Exception):
    """Raised when the Ollama daemon can't be reached or returns garbage.

    Callers should catch this and either skip the row (backfill) or
    surface a graceful "embeddings not configured" message (UI/API).
    """


# ── Vector serialization helpers ───────────────────────────────────────────
#
# We pack each vector as little-endian float32 into the BLOB column.
# Reasons for not using JSON or numpy bytes:
# - JSON is 3-5× larger and parses slowly.
# - numpy.tobytes() is identical to struct.pack but pulls in numpy as a
#   runtime dep that we don't otherwise need at this point.
# struct + memoryview is plenty fast for the 768-1024-dim vectors typical
# of nomic-embed-text / mxbai-embed-large.


def pack_vector(values: Iterable[float]) -> bytes:
    """Pack a vector of floats as little-endian float32 bytes."""
    floats = list(values)
    return struct.pack(f"<{len(floats)}f", *floats)


def unpack_vector(blob: bytes, dim: int) -> list[float]:
    """Inverse of pack_vector. ``dim`` is asserted against the actual length."""
    expected = dim * 4  # 4 bytes per float32
    if len(blob) != expected:
        raise ValueError(
            f"vector blob length {len(blob)} doesn't match dim={dim} (expected {expected})"
        )
    return list(struct.unpack(f"<{dim}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Pure-Python cosine similarity. Returns 0.0 if either vector is zero-length.

    For top-K retrieval over thousands of vectors we'd switch to a numpy
    matrix multiply or a vector index (sqlite-vss / hnsw); for round-1
    correctness the loop is fine.
    """
    if len(a) != len(b):
        raise ValueError(f"vector dim mismatch: {len(a)} vs {len(b)}")
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / ((na ** 0.5) * (nb ** 0.5))


# ── Ollama client ──────────────────────────────────────────────────────────


@dataclass
class OllamaClient:
    """Minimal Ollama HTTP wrapper for the embeddings endpoint.

    Designed to be created per-call (cheap) so test code can swap in a
    fake httpx transport without touching module-level state. Defaults
    pull from env vars; pass explicit ``base_url`` / ``model`` to override.
    """

    base_url: str | None = None
    model: str | None = None
    # Optional injectable httpx client (test plumbing).
    http: httpx.Client | None = None
    # Per-request timeout. Embeddings are normally <500ms but a cold
    # model load can take many seconds.
    timeout: float = 60.0

    def _url(self) -> str:
        return self.base_url or _env_url()

    def _model(self) -> str:
        return self.model or _env_model()

    def _client(self) -> httpx.Client:
        return self.http or httpx.Client(timeout=self.timeout)

    def embed_one(self, text: str) -> list[float]:
        """Embed a single text. Convenience wrapper around ``embed_batch``."""
        out = self.embed_batch([text])
        return out[0] if out else []

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed N texts. One HTTP request per text — Ollama's /api/embeddings
        endpoint is single-input, so we sequence them. Higher-throughput
        endpoints (/api/embed batch form) exist on newer Ollama versions
        but we keep to the lowest-common-denominator API for compatibility.

        Empty strings are kept in the output as empty vectors so callers
        can index back into the original list 1:1.
        """
        out: list[list[float]] = []
        # Open the client once so we get connection reuse across the loop.
        client = self._client()
        own = self.http is None
        try:
            for text in texts:
                if not text:
                    out.append([])
                    continue
                try:
                    r = client.post(
                        f"{self._url()}/api/embeddings",
                        json={"model": self._model(), "prompt": text},
                    )
                except httpx.HTTPError as e:
                    raise OllamaUnavailable(
                        f"could not reach Ollama at {self._url()}: {e}"
                    ) from e
                if r.status_code >= 400:
                    raise OllamaUnavailable(
                        f"Ollama returned HTTP {r.status_code}: {r.text[:200]}"
                    )
                try:
                    body = r.json()
                except ValueError as e:
                    raise OllamaUnavailable(
                        f"Ollama returned non-JSON: {r.text[:200]}"
                    ) from e
                vec = body.get("embedding")
                if not isinstance(vec, list):
                    raise OllamaUnavailable(
                        f"Ollama response missing 'embedding' list: {body}"
                    )
                out.append([float(x) for x in vec])
            return out
        finally:
            if own:
                client.close()
