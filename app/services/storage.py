"""
Google Cloud Storage service.
Handles PDF uploads, downloads, and ChromaDB persistence sync.
"""
import os
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

from google.cloud import storage
from google.cloud.storage import Bucket

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class StorageService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client: Optional[storage.Client] = None
        self._bucket: Optional[Bucket] = None

    @property
    def client(self) -> storage.Client:
        if self._client is None:
            if self.settings.GCP_CREDENTIALS_PATH:
                self._client = storage.Client.from_service_account_json(
                    self.settings.GCP_CREDENTIALS_PATH,
                    project=self.settings.GCP_PROJECT_ID,
                )
            else:
                self._client = storage.Client(project=self.settings.GCP_PROJECT_ID)
        return self._client

    @property
    def bucket(self) -> Bucket:
        if self._bucket is None:
            self._bucket = self.client.bucket(self.settings.GCS_BUCKET_NAME)
        return self._bucket

    async def upload_pdf(self, file_bytes: bytes, document_id: str, filename: str) -> str:
        """Upload a PDF to GCS and return the GCS URI."""
        blob_name = f"{self.settings.GCS_PDF_PREFIX}{document_id}/{filename}"
        blob = self.bucket.blob(blob_name)
        blob.content_type = "application/pdf"
        blob.upload_from_string(file_bytes, content_type="application/pdf")
        gcs_uri = f"gs://{self.settings.GCS_BUCKET_NAME}/{blob_name}"
        logger.info("pdf_uploaded", document_id=document_id, gcs_uri=gcs_uri, size_bytes=len(file_bytes))
        return gcs_uri

    async def download_pdf(self, document_id: str, filename: str) -> bytes:
        """Download a PDF from GCS."""
        blob_name = f"{self.settings.GCS_PDF_PREFIX}{document_id}/{filename}"
        blob = self.bucket.blob(blob_name)
        return blob.download_as_bytes()

    async def delete_pdf(self, document_id: str, filename: str) -> None:
        """Delete a PDF from GCS."""
        blob_name = f"{self.settings.GCS_PDF_PREFIX}{document_id}/{filename}"
        blob = self.bucket.blob(blob_name)
        blob.delete()
        logger.info("pdf_deleted", document_id=document_id, blob_name=blob_name)

    async def save_chroma_to_gcs(self, chroma_dir: str) -> None:
        """
        Tar + gzip the ChromaDB directory and upload to GCS.
        Called after every write to ensure persistence across Cloud Run instances.
        """
        if not os.path.exists(chroma_dir):
            logger.warning("chroma_dir_not_found", chroma_dir=chroma_dir)
            return

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                tar.add(chroma_dir, arcname="chroma_data")

            blob_name = f"{self.settings.GCS_CHROMA_PREFIX}chroma_snapshot.tar.gz"
            blob = self.bucket.blob(blob_name)
            blob.upload_from_filename(tmp_path)
            logger.info("chroma_saved_to_gcs", blob_name=blob_name)
        finally:
            os.unlink(tmp_path)

    async def load_chroma_from_gcs(self, chroma_dir: str) -> bool:
        """
        Download and extract ChromaDB snapshot from GCS.
        Returns True if snapshot existed and was restored, False otherwise.
        """
        blob_name = f"{self.settings.GCS_CHROMA_PREFIX}chroma_snapshot.tar.gz"
        blob = self.bucket.blob(blob_name)

        if not blob.exists():
            logger.info("no_chroma_snapshot_in_gcs")
            return False

        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            blob.download_to_filename(tmp_path)

            # Clear existing dir before extracting
            if os.path.exists(chroma_dir):
                shutil.rmtree(chroma_dir)
            os.makedirs(chroma_dir, exist_ok=True)

            parent_dir = str(Path(chroma_dir).parent)
            with tarfile.open(tmp_path, "r:gz") as tar:
                tar.extractall(parent_dir)

            # tar was created with arcname="chroma_data"; rename if needed
            extracted = os.path.join(parent_dir, "chroma_data")
            if extracted != chroma_dir and os.path.exists(extracted):
                if os.path.exists(chroma_dir):
                    shutil.rmtree(chroma_dir)
                shutil.move(extracted, chroma_dir)

            logger.info("chroma_restored_from_gcs", chroma_dir=chroma_dir)
            return True
        finally:
            os.unlink(tmp_path)

    async def list_documents(self) -> list[dict]:
        """List all PDF documents stored in GCS."""
        prefix = self.settings.GCS_PDF_PREFIX
        blobs = self.client.list_blobs(self.settings.GCS_BUCKET_NAME, prefix=prefix)
        documents = []
        for blob in blobs:
            parts = blob.name.removeprefix(prefix).split("/")
            if len(parts) >= 2:
                documents.append(
                    {
                        "document_id": parts[0],
                        "filename": parts[1],
                        "size_bytes": blob.size,
                        "created_at": blob.time_created,
                        "gcs_uri": f"gs://{self.settings.GCS_BUCKET_NAME}/{blob.name}",
                    }
                )
        return documents


_storage_service: Optional[StorageService] = None


def get_storage_service() -> StorageService:
    global _storage_service
    if _storage_service is None:
        _storage_service = StorageService()
    return _storage_service
