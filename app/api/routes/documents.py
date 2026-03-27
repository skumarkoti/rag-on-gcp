"""
Document management endpoints.
POST /documents/upload   → upload + async processing
GET  /documents/         → list all documents
GET  /documents/{id}     → get processing status
DELETE /documents/{id}   → delete document and its chunks
"""
import time
import uuid
from typing import Annotated

import structlog.contextvars
from fastapi import APIRouter, BackgroundTasks, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    DOCUMENTS_UPLOADED_TOTAL,
    DOCUMENT_PROCESSING_DURATION_SECONDS,
    DOCUMENT_PROCESSING_IN_PROGRESS,
)
from app.models.documents import (
    DocumentDeleteResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ProcessingStatus,
)
from app.services.document_registry import get_document_registry
from app.services.embeddings import get_embedding_service
from app.services.pdf_processor import get_pdf_processor
from app.services.storage import get_storage_service
from app.services.vector_store import get_vector_store_service

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger(__name__)
settings = get_settings()


async def _process_document_background(
    pdf_bytes: bytes,
    document_id: str,
    filename: str,
) -> None:
    """
    Background task: process PDF, generate embeddings, store in vector DB.
    Updates the document registry at each stage.
    """
    registry = get_document_registry()
    t_start = time.monotonic()
    DOCUMENT_PROCESSING_IN_PROGRESS.inc()

    structlog.contextvars.bind_contextvars(document_id=document_id)
    registry.update_status(document_id, ProcessingStatus.PROCESSING)

    try:
        # 1. Parse PDF and extract chunks
        processor = get_pdf_processor()
        result = await processor.process_pdf(pdf_bytes, document_id, filename)

        if not result.chunks:
            raise ValueError("No text could be extracted from this PDF")

        # 2. Generate embeddings in batches
        embedding_svc = get_embedding_service()
        texts = [c.text for c in result.chunks]
        logger.info("generating_embeddings", total_chunks=len(texts))
        embeddings = await embedding_svc.embed_texts(texts)

        # 3. Store in ChromaDB
        vector_store = get_vector_store_service()
        await vector_store.add_chunks(result.chunks, embeddings)

        elapsed = time.monotonic() - t_start
        DOCUMENT_PROCESSING_DURATION_SECONDS.observe(elapsed)
        DOCUMENTS_UPLOADED_TOTAL.labels(status="success").inc()

        registry.update_status(
            document_id,
            ProcessingStatus.COMPLETED,
            total_pages=result.total_pages,
            total_chunks=result.total_chunks,
            processing_time_seconds=elapsed,
        )
        logger.info(
            "document_processing_finished",
            document_id=document_id,
            total_pages=result.total_pages,
            total_chunks=result.total_chunks,
            duration_seconds=round(elapsed, 2),
        )

    except Exception as e:
        elapsed = time.monotonic() - t_start
        DOCUMENTS_UPLOADED_TOTAL.labels(status="failure").inc()
        registry.update_status(
            document_id,
            ProcessingStatus.FAILED,
            error_message=str(e),
        )
        logger.error(
            "document_processing_failed",
            document_id=document_id,
            error=str(e),
            duration_seconds=round(elapsed, 2),
        )
    finally:
        DOCUMENT_PROCESSING_IN_PROGRESS.dec()
        structlog.contextvars.unbind_contextvars("document_id")


@router.post(
    "/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a PDF document",
    description=(
        "Upload a PDF for processing. The file is stored in GCS immediately, "
        "then chunked, embedded, and indexed asynchronously. "
        "Poll GET /documents/{id} for processing status."
    ),
)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: Annotated[UploadFile, File(description="PDF file to upload")],
) -> DocumentUploadResponse:
    # Validate file type
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are supported",
        )

    pdf_bytes = await file.read()

    # Validate PDF content
    processor = get_pdf_processor()
    valid, error_msg = processor.validate_pdf(pdf_bytes, file.filename)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=error_msg,
        )

    document_id = str(uuid.uuid4())
    logger.info(
        "document_upload_received",
        document_id=document_id,
        filename=file.filename,
        size_bytes=len(pdf_bytes),
    )

    # Upload to GCS
    storage_svc = get_storage_service()
    gcs_uri = await storage_svc.upload_pdf(pdf_bytes, document_id, file.filename)

    # Register document
    registry = get_document_registry()
    registry.create(document_id, file.filename)

    # Queue background processing
    background_tasks.add_task(
        _process_document_background,
        pdf_bytes,
        document_id,
        file.filename,
    )

    return DocumentUploadResponse(
        document_id=document_id,
        filename=file.filename,
        status=ProcessingStatus.PENDING,
        message="Document uploaded successfully. Processing started in background.",
        gcs_uri=gcs_uri,
    )


@router.get(
    "/",
    response_model=DocumentListResponse,
    summary="List all documents",
)
async def list_documents() -> DocumentListResponse:
    registry = get_document_registry()
    docs = registry.list_all()
    return DocumentListResponse(documents=docs, total=len(docs))


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    summary="Get document processing status",
)
async def get_document_status(document_id: str) -> DocumentStatusResponse:
    registry = get_document_registry()
    doc = registry.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found",
        )
    return doc


@router.delete(
    "/{document_id}",
    response_model=DocumentDeleteResponse,
    summary="Delete a document and all its chunks",
)
async def delete_document(document_id: str) -> DocumentDeleteResponse:
    registry = get_document_registry()
    doc = registry.get(document_id)
    if not doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found",
        )

    # Delete chunks from vector store
    vector_store = get_vector_store_service()
    chunks_deleted = await vector_store.delete_document(document_id)

    # Delete PDF from GCS
    storage_svc = get_storage_service()
    await storage_svc.delete_pdf(document_id, doc.filename)

    # Invalidate cache
    from app.services.cache import get_cache_service
    await get_cache_service().invalidate_document(document_id)

    # Remove from registry
    registry.delete(document_id)

    logger.info(
        "document_deleted",
        document_id=document_id,
        filename=doc.filename,
        chunks_deleted=chunks_deleted,
    )

    return DocumentDeleteResponse(
        document_id=document_id,
        message=f"Document '{doc.filename}' deleted successfully",
        chunks_deleted=chunks_deleted,
    )
