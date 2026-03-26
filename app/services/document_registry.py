"""
In-memory document registry with GCS-backed persistence.
Tracks processing status, page counts, and timing for each document.
For production with multiple Cloud Run instances, this persists to GCS as JSON.
"""
import json
from datetime import datetime
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger
from app.models.documents import DocumentStatusResponse, ProcessingStatus

logger = get_logger(__name__)

_REGISTRY_BLOB = "metadata/document_registry.json"


class DocumentRegistry:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._store: dict[str, dict] = {}
        self._loaded = False

    def _get_bucket(self):
        from app.services.storage import get_storage_service
        return get_storage_service().bucket

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        try:
            blob = self._get_bucket().blob(_REGISTRY_BLOB)
            if blob.exists():
                self._store = json.loads(blob.download_as_text())
                logger.info("registry_loaded", documents=len(self._store))
        except Exception as e:
            logger.warning("registry_load_failed", error=str(e))

    def _save(self) -> None:
        try:
            blob = self._get_bucket().blob(_REGISTRY_BLOB)
            blob.upload_from_string(
                json.dumps(self._store, default=str),
                content_type="application/json",
            )
        except Exception as e:
            logger.warning("registry_save_failed", error=str(e))

    def create(self, document_id: str, filename: str) -> None:
        self._load()
        self._store[document_id] = {
            "document_id": document_id,
            "filename": filename,
            "status": ProcessingStatus.PENDING.value,
            "total_pages": None,
            "total_chunks": None,
            "processing_time_seconds": None,
            "error_message": None,
            "created_at": datetime.utcnow().isoformat(),
            "completed_at": None,
        }
        self._save()

    def update_status(
        self,
        document_id: str,
        status: ProcessingStatus,
        total_pages: Optional[int] = None,
        total_chunks: Optional[int] = None,
        processing_time_seconds: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        self._load()
        if document_id not in self._store:
            return
        record = self._store[document_id]
        record["status"] = status.value
        if total_pages is not None:
            record["total_pages"] = total_pages
        if total_chunks is not None:
            record["total_chunks"] = total_chunks
        if processing_time_seconds is not None:
            record["processing_time_seconds"] = round(processing_time_seconds, 2)
        if error_message is not None:
            record["error_message"] = error_message
        if status in (ProcessingStatus.COMPLETED, ProcessingStatus.FAILED):
            record["completed_at"] = datetime.utcnow().isoformat()
        self._save()

    def get(self, document_id: str) -> Optional[DocumentStatusResponse]:
        self._load()
        record = self._store.get(document_id)
        if not record:
            return None
        return DocumentStatusResponse(**record)

    def list_all(self) -> list[DocumentStatusResponse]:
        self._load()
        return [DocumentStatusResponse(**r) for r in self._store.values()]

    def delete(self, document_id: str) -> bool:
        self._load()
        if document_id in self._store:
            del self._store[document_id]
            self._save()
            return True
        return False

    def exists(self, document_id: str) -> bool:
        self._load()
        return document_id in self._store


_registry: Optional[DocumentRegistry] = None


def get_document_registry() -> DocumentRegistry:
    global _registry
    if _registry is None:
        _registry = DocumentRegistry()
    return _registry
