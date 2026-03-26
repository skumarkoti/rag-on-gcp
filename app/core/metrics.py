"""
Prometheus metrics definitions for the RAG application.
Covers document ingestion, query performance, vector store, and LLM calls.
"""
from prometheus_client import Counter, Gauge, Histogram, Info

# ── Application Info ──────────────────────────────────────────────────────────
APP_INFO = Info(
    "rag_app",
    "RAG application metadata",
)

# ── Document Ingestion ────────────────────────────────────────────────────────
DOCUMENTS_UPLOADED_TOTAL = Counter(
    "rag_documents_uploaded_total",
    "Total number of PDF documents uploaded",
    ["status"],  # success | failure
)

DOCUMENT_PAGES_PROCESSED_TOTAL = Counter(
    "rag_document_pages_processed_total",
    "Total pages processed across all documents",
)

DOCUMENT_CHUNKS_CREATED_TOTAL = Counter(
    "rag_document_chunks_created_total",
    "Total text chunks created and stored in vector DB",
)

DOCUMENT_PROCESSING_DURATION_SECONDS = Histogram(
    "rag_document_processing_duration_seconds",
    "Time to process a single PDF document (upload → embeddings → store)",
    buckets=[1, 5, 10, 30, 60, 120, 300, 600],
)

DOCUMENT_PROCESSING_IN_PROGRESS = Gauge(
    "rag_document_processing_in_progress",
    "Number of documents currently being processed",
)

# ── Query / RAG ───────────────────────────────────────────────────────────────
QUERY_REQUESTS_TOTAL = Counter(
    "rag_query_requests_total",
    "Total RAG query requests",
    ["status"],  # success | failure
)

QUERY_DURATION_SECONDS = Histogram(
    "rag_query_duration_seconds",
    "End-to-end RAG query latency",
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

QUERY_RETRIEVED_CHUNKS = Histogram(
    "rag_query_retrieved_chunks",
    "Number of chunks retrieved per query",
    buckets=[1, 2, 3, 5, 8, 10, 15, 20],
)

# ── Embeddings ────────────────────────────────────────────────────────────────
EMBEDDING_REQUESTS_TOTAL = Counter(
    "rag_embedding_requests_total",
    "Total Vertex AI embedding API calls",
    ["status"],
)

EMBEDDING_DURATION_SECONDS = Histogram(
    "rag_embedding_duration_seconds",
    "Vertex AI embedding API call latency",
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

EMBEDDING_TEXTS_PER_REQUEST = Histogram(
    "rag_embedding_texts_per_request",
    "Number of texts per embedding batch",
    buckets=[1, 10, 25, 50, 100, 200],
)

# ── LLM ──────────────────────────────────────────────────────────────────────
LLM_REQUESTS_TOTAL = Counter(
    "rag_llm_requests_total",
    "Total Vertex AI Gemini API calls",
    ["status", "model"],
)

LLM_DURATION_SECONDS = Histogram(
    "rag_llm_duration_seconds",
    "Vertex AI Gemini API call latency",
    buckets=[0.5, 1.0, 2.5, 5.0, 10.0, 20.0, 60.0],
)

LLM_INPUT_TOKENS_TOTAL = Counter(
    "rag_llm_input_tokens_total",
    "Total input tokens sent to LLM",
)

LLM_OUTPUT_TOKENS_TOTAL = Counter(
    "rag_llm_output_tokens_total",
    "Total output tokens received from LLM",
)

# ── Vector Store ──────────────────────────────────────────────────────────────
VECTOR_STORE_TOTAL_CHUNKS = Gauge(
    "rag_vector_store_total_chunks",
    "Total chunks currently stored in ChromaDB",
)

VECTOR_STORE_SEARCH_DURATION_SECONDS = Histogram(
    "rag_vector_store_search_duration_seconds",
    "ChromaDB similarity search latency",
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0],
)

# ── Cache ─────────────────────────────────────────────────────────────────────
CACHE_HITS_TOTAL = Counter(
    "rag_cache_hits_total",
    "Total cache hits for query results",
)

CACHE_MISSES_TOTAL = Counter(
    "rag_cache_misses_total",
    "Total cache misses for query results",
)


def init_app_info(app_name: str, version: str, environment: str) -> None:
    APP_INFO.info(
        {
            "name": app_name,
            "version": version,
            "environment": environment,
        }
    )
