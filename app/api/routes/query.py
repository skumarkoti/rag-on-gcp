"""
RAG query endpoint.
POST /query  → retrieve relevant chunks + generate LLM answer
"""
import time

import structlog.contextvars
from fastapi import APIRouter, HTTPException, status

from app.core.logging import get_logger
from app.core.metrics import (
    QUERY_REQUESTS_TOTAL,
    QUERY_DURATION_SECONDS,
    QUERY_RETRIEVED_CHUNKS,
)
from app.models.query import QueryRequest, QueryResponse, SourceChunk
from app.services.cache import get_cache_service
from app.services.embeddings import get_embedding_service
from app.services.llm import get_llm_service
from app.services.vector_store import get_vector_store_service

router = APIRouter(prefix="/query", tags=["query"])
logger = get_logger(__name__)


@router.post(
    "/",
    response_model=QueryResponse,
    summary="Query documents using RAG",
    description=(
        "Submit a natural language question. The system retrieves the most "
        "relevant document chunks, then uses Gemini to generate a grounded answer."
    ),
)
async def query_documents(request: QueryRequest) -> QueryResponse:
    t_start = time.monotonic()
    structlog.contextvars.bind_contextvars(question_preview=request.question[:80])

    try:
        # 1. Check cache
        cache = get_cache_service()
        cached_result = await cache.get(
            request.question, request.top_k, request.document_ids
        )
        if cached_result:
            elapsed_ms = (time.monotonic() - t_start) * 1000
            QUERY_REQUESTS_TOTAL.labels(status="success").inc()
            return QueryResponse(**cached_result, cached=True, latency_ms=round(elapsed_ms, 1))

        # 2. Embed the query
        embedding_svc = get_embedding_service()
        query_embedding = await embedding_svc.embed_query(request.question)

        # 3. Retrieve similar chunks from ChromaDB
        vector_store = get_vector_store_service()

        if vector_store.get_total_chunks() == 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="No documents have been indexed yet. Please upload PDFs first.",
            )

        retrieved = await vector_store.search(
            query_embedding=query_embedding,
            top_k=request.top_k,
            score_threshold=request.score_threshold,
            document_ids=request.document_ids,
        )

        QUERY_RETRIEVED_CHUNKS.observe(len(retrieved))
        logger.info(
            "chunks_retrieved",
            count=len(retrieved),
            top_score=retrieved[0]["similarity_score"] if retrieved else 0,
        )

        # 4. Generate answer with Gemini
        llm_svc = get_llm_service()
        answer, used_chunks = await llm_svc.generate_answer(request.question, retrieved)

        # 5. Build source list
        sources: list[SourceChunk] = []
        if request.include_sources:
            for chunk in used_chunks:
                meta = chunk.get("metadata", {})
                sources.append(
                    SourceChunk(
                        document_id=meta.get("document_id", ""),
                        filename=meta.get("filename", ""),
                        page_number=meta.get("page_number", 0),
                        chunk_index=meta.get("chunk_index", 0),
                        content=chunk.get("text", ""),
                        similarity_score=chunk.get("similarity_score", 0.0),
                    )
                )

        elapsed_ms = (time.monotonic() - t_start) * 1000
        QUERY_DURATION_SECONDS.observe(elapsed_ms / 1000)
        QUERY_REQUESTS_TOTAL.labels(status="success").inc()

        response_data = {
            "question": request.question,
            "answer": answer,
            "sources": [s.model_dump() for s in sources],
            "total_chunks_retrieved": len(retrieved),
            "latency_ms": round(elapsed_ms, 1),
        }

        # Store in cache (without cached=True flag)
        await cache.set(request.question, request.top_k, request.document_ids, response_data)

        logger.info(
            "query_completed",
            latency_ms=round(elapsed_ms, 1),
            chunks_retrieved=len(retrieved),
            answer_length=len(answer),
        )

        return QueryResponse(**response_data, cached=False)

    except HTTPException:
        QUERY_REQUESTS_TOTAL.labels(status="failure").inc()
        raise
    except Exception as e:
        QUERY_REQUESTS_TOTAL.labels(status="failure").inc()
        elapsed_ms = (time.monotonic() - t_start) * 1000
        logger.error(
            "query_failed",
            error=str(e),
            latency_ms=round(elapsed_ms, 1),
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Query processing failed: {str(e)}",
        )
    finally:
        structlog.contextvars.unbind_contextvars("question_preview")
