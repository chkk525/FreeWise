"""Tests for the /metrics Prometheus exposition endpoint."""

from __future__ import annotations


class TestMetricsEndpoint:
    def test_returns_prometheus_text(self, client):
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/plain")
        # Prometheus format: HELP / TYPE / metric lines
        assert "# HELP freewise_highlights_total" in resp.text
        assert "# TYPE freewise_highlights_total gauge" in resp.text
        assert "freewise_up 1" in resp.text

    def test_counts_reflect_db_state(self, client, make_highlight):
        make_highlight(text="active")
        make_highlight(text="active fav", is_favorited=True)
        make_highlight(text="trashed", is_discarded=True)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        # Three lines must appear with correct values.
        assert "freewise_highlights_total 3" in resp.text
        assert "freewise_highlights_active 2" in resp.text
        assert "freewise_highlights_favorited 1" in resp.text

    def test_embedding_coverage_when_partial(self, client, db, make_highlight):
        from app.models import Embedding
        from app.services.embeddings import pack_vector
        h1 = make_highlight(text="a")
        make_highlight(text="b")
        db.add(Embedding(highlight_id=h1.id, model_name="nomic-embed-text",
                         dim=1, vector=pack_vector([1.0])))
        db.commit()
        resp = client.get("/metrics")
        assert resp.status_code == 200
        # 1 of 2 active = 0.5 coverage with the configured model label.
        assert 'freewise_embeddings_count{model="nomic-embed-text"} 1' in resp.text
        assert 'freewise_embedding_coverage{model="nomic-embed-text"} 0.5' in resp.text

    def test_no_auth_required(self, client):
        # No Authorization header → still 200. Same posture as /healthz.
        resp = client.get("/metrics")
        assert resp.status_code == 200

    def test_books_count(self, client, make_book):
        make_book(title="One")
        make_book(title="Two")
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "freewise_books_total 2" in resp.text
