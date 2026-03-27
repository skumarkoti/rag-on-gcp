"""Pydantic models for RAG query requests and responses."""
from typing import Optional

from pydantic import BaseModel, Field


class QueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=2000,
        description="The question to answer using the RAG pipeline",
    )
    top_k: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of document chunks to retrieve",
    )
    score_threshold: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for retrieved chunks",
    )
    document_ids: Optional[list[str]] = Field(
        default=None,
        description="Filter results to specific document IDs (None = all documents)",
    )
    include_sources: bool = Field(
        default=True,
        description="Include source chunk details in the response",
    )


class SourceChunk(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    content: str
    similarity_score: float


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceChunk]
    total_chunks_retrieved: int
    cached: bool = False
    latency_ms: float


class QueryHealthResponse(BaseModel):
    status: str
    vector_store_chunks: int
    llm_model: str
    embedding_model: str
