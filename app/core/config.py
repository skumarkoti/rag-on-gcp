"""
Application configuration using Pydantic Settings.
All values can be overridden via environment variables.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────────────────────
    APP_NAME: str = "RAG on GCP"
    APP_VERSION: str = "1.0.0"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    LOG_LEVEL: str = "INFO"
    DEBUG: bool = False

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    WORKERS: int = 1  # Cloud Run manages concurrency; keep 1 worker per instance
    MAX_CONCURRENT_REQUESTS: int = 25  # Per Cloud Run instance

    # ── GCP ──────────────────────────────────────────────────────────────────
    GCP_PROJECT_ID: str = Field(..., description="GCP Project ID")
    GCP_REGION: str = "us-central1"
    GCP_CREDENTIALS_PATH: str = ""  # Leave empty to use ADC

    # ── Cloud Storage ────────────────────────────────────────────────────────
    GCS_BUCKET_NAME: str = Field(..., description="GCS bucket for PDFs and ChromaDB")
    GCS_PDF_PREFIX: str = "pdfs/"
    GCS_CHROMA_PREFIX: str = "chroma/"

    # ── Vertex AI ────────────────────────────────────────────────────────────
    VERTEX_AI_LOCATION: str = "us-central1"
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768
    EMBEDDING_BATCH_SIZE: int = 100  # Max texts per embedding API call
    LLM_MODEL: str = "gemini-1.5-pro-002"
    LLM_MAX_TOKENS: int = 8192
    LLM_TEMPERATURE: float = 0.1

    # ── Vector Store (ChromaDB) ───────────────────────────────────────────────
    CHROMA_PERSIST_DIR: str = "/tmp/chroma_data"
    CHROMA_COLLECTION_NAME: str = "rag_documents"
    CHROMA_SYNC_TO_GCS: bool = True  # Sync ChromaDB to GCS on writes

    # ── PDF Processing ───────────────────────────────────────────────────────
    PDF_CHUNK_SIZE: int = 1000          # Tokens per chunk
    PDF_CHUNK_OVERLAP: int = 200        # Token overlap between chunks
    PDF_MAX_FILE_SIZE_MB: int = 500     # Max upload size
    PDF_PROCESSING_BATCH_SIZE: int = 50 # Pages processed per batch

    # ── Redis (Query Cache) ──────────────────────────────────────────────────
    REDIS_URL: str = ""  # e.g. redis://localhost:6379; empty = no caching
    CACHE_TTL_SECONDS: int = 3600

    # ── RAG ──────────────────────────────────────────────────────────────────
    RAG_TOP_K: int = 5                  # Top-K chunks to retrieve
    RAG_SCORE_THRESHOLD: float = 0.3    # Minimum similarity score
    RAG_MAX_CONTEXT_TOKENS: int = 12000 # Max tokens for context window

    # ── Monitoring ───────────────────────────────────────────────────────────
    METRICS_ENABLED: bool = True
    METRICS_PATH: str = "/metrics"
    TRACING_ENABLED: bool = False       # Enable Cloud Trace (adds latency in dev)

    @field_validator("LOG_LEVEL")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"LOG_LEVEL must be one of {valid}")
        return upper

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT == "production"

    @property
    def pdf_max_bytes(self) -> int:
        return self.PDF_MAX_FILE_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
