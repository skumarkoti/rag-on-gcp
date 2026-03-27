"""
Redis query cache service.
Caches RAG query results to reduce LLM and embedding costs for repeated queries.
Falls back gracefully when Redis is unavailable.
"""
import hashlib
import json
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import CACHE_HITS_TOTAL, CACHE_MISSES_TOTAL

logger = get_logger(__name__)


class CacheService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._redis = None
        self._available = False
        self._initialized = False

    def _init_redis(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        if not self.settings.REDIS_URL:
            logger.info("cache_disabled", reason="REDIS_URL not set")
            return
        try:
            import redis
            client = redis.from_url(
                self.settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            client.ping()
            self._redis = client
            self._available = True
            logger.info("cache_connected", url=self.settings.REDIS_URL)
        except Exception as e:
            logger.warning("cache_unavailable", error=str(e))

    @staticmethod
    def _make_key(question: str, top_k: int, document_ids: Optional[list[str]]) -> str:
        doc_part = ",".join(sorted(document_ids)) if document_ids else "all"
        raw = f"{question}|{top_k}|{doc_part}"
        return "rag:" + hashlib.sha256(raw.encode()).hexdigest()

    async def get(
        self,
        question: str,
        top_k: int,
        document_ids: Optional[list[str]],
    ) -> Optional[dict]:
        self._init_redis()
        if not self._available:
            return None
        key = self._make_key(question, top_k, document_ids)
        try:
            value = self._redis.get(key)
            if value:
                CACHE_HITS_TOTAL.inc()
                logger.debug("cache_hit", key=key)
                return json.loads(value)
        except Exception as e:
            logger.warning("cache_get_error", error=str(e))
        CACHE_MISSES_TOTAL.inc()
        return None

    async def set(
        self,
        question: str,
        top_k: int,
        document_ids: Optional[list[str]],
        data: dict,
    ) -> None:
        self._init_redis()
        if not self._available:
            return
        key = self._make_key(question, top_k, document_ids)
        try:
            self._redis.setex(key, self.settings.CACHE_TTL_SECONDS, json.dumps(data))
            logger.debug("cache_set", key=key, ttl=self.settings.CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning("cache_set_error", error=str(e))

    async def invalidate_document(self, document_id: str) -> None:
        """Flush all cache entries (simple strategy — no per-doc tracking)."""
        self._init_redis()
        if not self._available:
            return
        try:
            keys = self._redis.keys("rag:*")
            if keys:
                self._redis.delete(*keys)
                logger.info("cache_invalidated", keys_deleted=len(keys))
        except Exception as e:
            logger.warning("cache_invalidation_error", error=str(e))


_cache_service: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
