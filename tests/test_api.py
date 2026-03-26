"""
Integration tests for the RAG API.
Uses httpx.AsyncClient with the FastAPI test app.

Run with:
    pytest tests/ -v
"""
import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# Set required env vars before importing the app
import os
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("CHROMA_SYNC_TO_GCS", "false")
os.environ.setdefault("ENVIRONMENT", "local")


@pytest.fixture(scope="module")
def client():
    from app.main import app
    with TestClient(app) as c:
        yield c


def test_liveness(client):
    resp = client.get("/api/v1/health/live")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_info_endpoint(client):
    resp = client.get("/api/v1/health/info")
    assert resp.status_code == 200
    data = resp.json()
    assert "version" in data
    assert "llm_model" in data


def test_upload_invalid_file_type(client):
    resp = client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.txt", b"hello world", "text/plain")},
    )
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


def test_query_empty_vector_store(client):
    """Querying before any documents are indexed should return a 422."""
    with patch(
        "app.services.vector_store.get_vector_store_service"
    ) as mock_vs_factory:
        mock_vs = MagicMock()
        mock_vs.get_total_chunks.return_value = 0
        mock_vs_factory.return_value = mock_vs

        with patch("app.services.embeddings.get_embedding_service") as mock_emb:
            mock_emb.return_value.embed_query = AsyncMock(return_value=[0.1] * 768)

            resp = client.post(
                "/api/v1/query/",
                json={"question": "What is this about?"},
            )
            assert resp.status_code == 422


def test_list_documents_empty(client):
    with patch("app.services.document_registry.get_document_registry") as mock_reg:
        mock_reg.return_value.list_all.return_value = []
        resp = client.get("/api/v1/documents/")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0


def test_get_nonexistent_document(client):
    with patch("app.services.document_registry.get_document_registry") as mock_reg:
        mock_reg.return_value.get.return_value = None
        resp = client.get("/api/v1/documents/does-not-exist")
        assert resp.status_code == 404


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert b"rag_" in resp.content or b"python_" in resp.content
