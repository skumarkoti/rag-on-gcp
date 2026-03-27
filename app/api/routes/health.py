"""
Health and readiness endpoints.
/health/live  → liveness  (is the process running?)
/health/ready → readiness (are dependencies available?)
/health/info  → application metadata
"""
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.logging import get_logger

router = APIRouter(prefix="/health", tags=["health"])
logger = get_logger(__name__)


class LivenessResponse(BaseModel):
    status: str


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]


class InfoResponse(BaseModel):
    name: str
    version: str
    environment: str
    llm_model: str
    embedding_model: str
    vector_store: str


@router.get("/live", response_model=LivenessResponse, summary="Liveness probe")
async def liveness() -> LivenessResponse:
    """Returns 200 if the process is alive. Used by Cloud Run liveness probe."""
    return LivenessResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness() -> ReadinessResponse:
    """
    Checks that all critical dependencies are reachable.
    Returns 200 if ready to serve traffic, 503 otherwise.
    """
    from fastapi import HTTPException
    from app.services.vector_store import get_vector_store_service

    checks: dict[str, str] = {}

    # Check ChromaDB
    try:
        vs = get_vector_store_service()
        count = vs.get_total_chunks()
        checks["chromadb"] = f"ok (chunks={count})"
    except Exception as e:
        checks["chromadb"] = f"error: {e}"

    # Check GCS connectivity
    try:
        from app.services.storage import get_storage_service
        storage = get_storage_service()
        _ = storage.bucket
        checks["gcs"] = "ok"
    except Exception as e:
        checks["gcs"] = f"error: {e}"

    failed = [k for k, v in checks.items() if v.startswith("error")]
    if failed:
        logger.warning("readiness_check_failed", failed_checks=failed)
        raise HTTPException(status_code=503, detail={"status": "not_ready", "checks": checks})

    return ReadinessResponse(status="ready", checks=checks)


@router.get("/info", response_model=InfoResponse, summary="Application info")
async def info() -> InfoResponse:
    settings = get_settings()
    return InfoResponse(
        name=settings.APP_NAME,
        version=settings.APP_VERSION,
        environment=settings.ENVIRONMENT,
        llm_model=settings.LLM_MODEL,
        embedding_model=settings.EMBEDDING_MODEL,
        vector_store=f"chromadb:{settings.CHROMA_COLLECTION_NAME}",
    )
