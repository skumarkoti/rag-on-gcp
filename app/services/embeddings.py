"""
Vertex AI text embedding service.
Batches embedding requests to stay within API limits and tracks metrics.
"""
import time
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    EMBEDDING_REQUESTS_TOTAL,
    EMBEDDING_DURATION_SECONDS,
    EMBEDDING_TEXTS_PER_REQUEST,
)

logger = get_logger(__name__)


class EmbeddingService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: Optional[TextEmbeddingModel] = None

    @property
    def model(self) -> TextEmbeddingModel:
        if self._model is None:
            import vertexai
            vertexai.init(
                project=self.settings.GCP_PROJECT_ID,
                location=self.settings.VERTEX_AI_LOCATION,
            )
            self._model = TextEmbeddingModel.from_pretrained(self.settings.EMBEDDING_MODEL)
            logger.info("embedding_model_loaded", model=self.settings.EMBEDDING_MODEL)
        return self._model

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Call Vertex AI embedding API for a single batch of texts."""
        inputs = [
            TextEmbeddingInput(text=t, task_type="RETRIEVAL_DOCUMENT")
            for t in texts
        ]
        t0 = time.monotonic()
        embeddings = self.model.get_embeddings(inputs)
        elapsed = time.monotonic() - t0

        EMBEDDING_DURATION_SECONDS.observe(elapsed)
        EMBEDDING_TEXTS_PER_REQUEST.observe(len(texts))
        EMBEDDING_REQUESTS_TOTAL.labels(status="success").inc()

        return [e.values for e in embeddings]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """
        Embed a list of texts using Vertex AI, processing in batches.
        Returns embeddings in the same order as input texts.
        """
        if not texts:
            return []

        batch_size = self.settings.EMBEDDING_BATCH_SIZE
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            logger.debug(
                "embedding_batch",
                batch_index=i // batch_size,
                batch_size=len(batch),
                total_texts=len(texts),
            )
            try:
                batch_embeddings = self._embed_batch(batch)
                all_embeddings.extend(batch_embeddings)
            except Exception as e:
                EMBEDDING_REQUESTS_TOTAL.labels(status="failure").inc()
                logger.error("embedding_batch_failed", error=str(e), batch_start=i)
                raise

        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single query string (uses RETRIEVAL_QUERY task type)."""
        inputs = [TextEmbeddingInput(text=query, task_type="RETRIEVAL_QUERY")]
        t0 = time.monotonic()
        try:
            result = self.model.get_embeddings(inputs)
            elapsed = time.monotonic() - t0
            EMBEDDING_DURATION_SECONDS.observe(elapsed)
            EMBEDDING_REQUESTS_TOTAL.labels(status="success").inc()
            return result[0].values
        except Exception as e:
            EMBEDDING_REQUESTS_TOTAL.labels(status="failure").inc()
            logger.error("query_embedding_failed", error=str(e))
            raise


_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
