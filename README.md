# RAG on GCP

Production-grade Retrieval-Augmented Generation (RAG) application on Google Cloud Run.

## Architecture

```
                    ┌─────────────────────────────────────────┐
                    │           Google Cloud Run               │
                    │                                          │
  Users (20–50)  ──▶│  FastAPI App  ──▶  ChromaDB (local)     │
                    │       │                    │             │
                    │       ▼                    ▼             │
                    │  Vertex AI Gemini    GCS (persistence)   │
                    │  text-embedding-004                      │
                    └──────────────┬──────────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────────┐
                    │  Cloud Memorystore Redis (query cache)   │
                    └─────────────────────────────────────────┘
                    ┌─────────────────────────────────────────┐
                    │  Monitoring: Prometheus + Grafana        │
                    │  Logging:   Cloud Logging (JSON)         │
                    └─────────────────────────────────────────┘
```

### Key Design Decisions

| Concern | Solution |
|---|---|
| 20-50 concurrent users | Cloud Run: min 2 instances × 25 concurrency = 50 guaranteed |
| 1000+ page PDFs | Batch page processing (50 pages/batch), batch embedding (100 texts/call) |
| Cross-instance persistence | ChromaDB snapshots synced to GCS on every write |
| Query cost reduction | Redis query cache (1hr TTL) |
| LLM | Vertex AI Gemini 1.5 Pro |
| Embeddings | Vertex AI text-embedding-004 (768 dim) |
| Observability | Prometheus metrics, Grafana dashboards, structured JSON logs |

## Prerequisites

- GCP project with billing enabled
- `gcloud` CLI authenticated (`gcloud auth login`)
- Docker (for local dev and building images)
- Terraform >= 1.6

## Quick Start

### 1. Bootstrap GCP (one-time)

```bash
chmod +x scripts/*.sh
./scripts/setup.sh YOUR_PROJECT_ID us-central1
```

### 2. Configure Terraform

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your project details
```

### 3. Deploy

```bash
./scripts/deploy.sh YOUR_PROJECT_ID us-central1
```

The script will:
1. Build and push the Docker image to Artifact Registry
2. Apply Terraform (creates all GCP resources)
3. Run a smoke test against the live endpoint

## Local Development

```bash
cp .env.example .env
# Fill in GCP_PROJECT_ID and GCS_BUCKET_NAME

# Start full stack (app + Redis + Prometheus + Grafana)
./scripts/local_dev.sh up

# App:        http://localhost:8080/docs
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3000  (admin / admin)
```

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| POST | `/api/v1/documents/upload` | Upload a PDF (async processing) |
| GET  | `/api/v1/documents/` | List all documents |
| GET  | `/api/v1/documents/{id}` | Get processing status |
| DELETE | `/api/v1/documents/{id}` | Delete document |
| POST | `/api/v1/query/` | Query documents with RAG |
| GET  | `/api/v1/health/live` | Liveness probe |
| GET  | `/api/v1/health/ready` | Readiness probe |
| GET  | `/metrics` | Prometheus metrics |

### Upload a PDF

```bash
curl -X POST https://YOUR_APP_URL/api/v1/documents/upload \
     -F "file=@your-document.pdf"
# Returns: {"document_id": "...", "status": "pending"}
```

### Check processing status

```bash
curl https://YOUR_APP_URL/api/v1/documents/{document_id}
# Returns: {"status": "completed", "total_pages": 312, "total_chunks": 1847}
```

### Query

```bash
curl -X POST https://YOUR_APP_URL/api/v1/query/ \
     -H "Content-Type: application/json" \
     -d '{"question": "What are the key findings?", "top_k": 5}'
```

## Configuration Reference

See `.env.example` for all configuration options. Key variables:

| Variable | Default | Description |
|---|---|---|
| `GCP_PROJECT_ID` | — | **Required.** GCP project |
| `GCS_BUCKET_NAME` | — | **Required.** GCS bucket |
| `LLM_MODEL` | `gemini-1.5-pro-002` | Gemini model |
| `PDF_CHUNK_SIZE` | `1000` | Tokens per chunk |
| `RAG_TOP_K` | `5` | Chunks retrieved per query |
| `REDIS_URL` | empty | Redis for caching (optional) |
| `CHROMA_SYNC_TO_GCS` | `true` | Persist ChromaDB to GCS |

## Monitoring

### Prometheus Metrics

| Metric | Type | Description |
|---|---|---|
| `rag_query_duration_seconds` | Histogram | End-to-end query latency |
| `rag_query_requests_total` | Counter | Queries by status |
| `rag_documents_uploaded_total` | Counter | Uploads by status |
| `rag_document_processing_duration_seconds` | Histogram | PDF processing time |
| `rag_llm_duration_seconds` | Histogram | Gemini call latency |
| `rag_llm_input_tokens_total` | Counter | Total input tokens |
| `rag_vector_store_total_chunks` | Gauge | Chunks in ChromaDB |
| `rag_cache_hits_total` | Counter | Redis cache hits |

### Grafana Dashboard

The pre-built dashboard (`monitoring/grafana/dashboards/rag_overview.json`) shows:
- Application status, chunk count, query rate, P95 latency, error rate
- Query latency percentiles (P50/P90/P95/P99)
- LLM call latency and token usage
- Document ingestion throughput
- Cache hit rate

## Running Tests

```bash
pip install -r requirements-dev.txt
pytest tests/ -v --cov=app --cov-report=term-missing
```

## Infrastructure

Terraform manages:
- **Cloud Run** — RAG app (auto-scaling) + Grafana
- **Artifact Registry** — Docker images
- **Cloud Storage** — PDFs + ChromaDB snapshots
- **Cloud Memorystore** — Redis cache
- **VPC + Serverless VPC Connector** — Private networking
- **Secret Manager** — Sensitive config
- **Cloud Monitoring** — Alerting policies

To destroy all resources:
```bash
cd infra/terraform
terraform destroy
```
