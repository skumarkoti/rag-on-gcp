"""
ChromaDB vector store service.
Handles storing, querying, and deleting document chunks.
Optionally syncs to GCS after writes for cross-instance persistence.
"""
import asyncio
import time
from typing import Optional

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    VECTOR_STORE_TOTAL_CHUNKS,
    VECTOR_STORE_SEARCH_DURATION_SECONDS,
)
from app.services.pdf_processor import TextChunk

logger = get_logger(__name__)


class VectorStoreService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[chromadb.Client] = None
        self._collection: Optional[chromadb.Collection] = None

    @property
    def client(self) -> chromadb.Client:
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=self.settings.CHROMA_PERSIST_DIR,
                settings=ChromaSettings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
            logger.info(
                "chroma_client_initialized",
                persist_dir=self.settings.CHROMA_PERSIST_DIR,
            )
        return self._client

    @property
    def collection(self) -> chromadb.Collection:
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.settings.CHROMA_COLLECTION_NAME,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info(
                "chroma_collection_ready",
                name=self.settings.CHROMA_COLLECTION_NAME,
                count=self._collection.count(),
            )
            VECTOR_STORE_TOTAL_CHUNKS.set(self._collection.count())
        return self._collection

    async def add_chunks(
        self,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add text chunks with pre-computed embeddings to the vector store.
        Inserts in batches of 500 to stay within ChromaDB limits.
        """
        if not chunks:
            return

        BATCH_SIZE = 500
        ids = [f"{c.document_id}_{c.chunk_index}" for c in chunks]
        documents = [c.text for c in chunks]
        metadatas = [
            {
                "document_id": c.document_id,
                "filename": c.filename,
                "page_number": c.page_number,
                "chunk_index": c.chunk_index,
                "char_start": c.char_start,
                "char_end": c.char_end,
            }
            for c in chunks
        ]

        for start in range(0, len(chunks), BATCH_SIZE):
            end = min(start + BATCH_SIZE, len(chunks))
            self.collection.add(
                ids=ids[start:end],
                documents=documents[start:end],
                embeddings=embeddings[start:end],
                metadatas=metadatas[start:end],
            )
            logger.debug(
                "chunks_added_to_chroma",
                batch=f"{start}-{end}",
                total=len(chunks),
            )

        total = self.collection.count()
        VECTOR_STORE_TOTAL_CHUNKS.set(total)
        logger.info(
            "vector_store_updated",
            chunks_added=len(chunks),
            total_chunks=total,
        )

        if self.settings.CHROMA_SYNC_TO_GCS:
            # Fire-and-forget GCS sync (don't block the request)
            asyncio.create_task(self._sync_to_gcs())

    async def _sync_to_gcs(self) -> None:
        from app.services.storage import get_storage_service
        try:
            await get_storage_service().save_chroma_to_gcs(self.settings.CHROMA_PERSIST_DIR)
        except Exception as e:
            logger.error("chroma_gcs_sync_failed", error=str(e))

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        score_threshold: float = 0.3,
        document_ids: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        Perform similarity search.
        Returns list of results with text, metadata, and similarity score.
        """
        where: Optional[dict] = None
        if document_ids:
            if len(document_ids) == 1:
                where = {"document_id": document_ids[0]}
            else:
                where = {"document_id": {"$in": document_ids}}

        t0 = time.monotonic()
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, max(self.collection.count(), 1)),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        elapsed = time.monotonic() - t0
        VECTOR_STORE_SEARCH_DURATION_SECONDS.observe(elapsed)

        hits = []
        if not results["ids"] or not results["ids"][0]:
            return hits

        for doc_id, doc, meta, dist in zip(
            results["ids"][0],
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            # ChromaDB cosine distance → similarity: 1 - distance/2 (range 0-1)
            similarity = 1.0 - (dist / 2.0)
            if similarity >= score_threshold:
                hits.append(
                    {
                        "id": doc_id,
                        "text": doc,
                        "metadata": meta,
                        "similarity_score": round(similarity, 4),
                    }
                )

        return sorted(hits, key=lambda x: x["similarity_score"], reverse=True)

    async def delete_document(self, document_id: str) -> int:
        """Delete all chunks for a document. Returns the number of chunks deleted."""
        results = self.collection.get(where={"document_id": document_id})
        ids_to_delete = results["ids"]
        if ids_to_delete:
            self.collection.delete(ids=ids_to_delete)
            total = self.collection.count()
            VECTOR_STORE_TOTAL_CHUNKS.set(total)
            logger.info(
                "document_deleted_from_vector_store",
                document_id=document_id,
                chunks_deleted=len(ids_to_delete),
            )
            if self.settings.CHROMA_SYNC_TO_GCS:
                asyncio.create_task(self._sync_to_gcs())
        return len(ids_to_delete)

    def get_total_chunks(self) -> int:
        return self.collection.count()

    async def reset(self) -> None:
        """Drop and recreate the collection. Use with caution."""
        self.client.delete_collection(self.settings.CHROMA_COLLECTION_NAME)
        self._collection = None
        _ = self.collection  # Recreate
        logger.warning("vector_store_reset")


_vector_store_service: Optional[VectorStoreService] = None


def get_vector_store_service() -> VectorStoreService:
    global _vector_store_service
    if _vector_store_service is None:
        _vector_store_service = VectorStoreService()
    return _vector_store_service
