"""Pydantic models for document ingestion and management."""
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class ProcessingStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    status: ProcessingStatus
    message: str
    gcs_uri: Optional[str] = None
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentStatusResponse(BaseModel):
    document_id: str
    filename: str
    status: ProcessingStatus
    total_pages: Optional[int] = None
    total_chunks: Optional[int] = None
    processing_time_seconds: Optional[float] = None
    error_message: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class DocumentListResponse(BaseModel):
    documents: list[DocumentStatusResponse]
    total: int


class DocumentDeleteResponse(BaseModel):
    document_id: str
    message: str
    chunks_deleted: int


class ChunkMetadata(BaseModel):
    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    total_chunks: int
    char_start: int
    char_end: int
