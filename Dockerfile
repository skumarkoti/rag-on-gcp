# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

# System deps for PyMuPDF and ChromaDB
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

WORKDIR /app

# System runtime libs
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    mkdir -p /tmp/chroma_data && \
    chown -R appuser:appuser /tmp/chroma_data /app

# Copy application source
COPY --chown=appuser:appuser app/ ./app/

USER appuser

# Cloud Run uses PORT env var; default 8080
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app

EXPOSE 8080

# Health check (Cloud Run also configures this via the service YAML)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:${PORT}/api/v1/health/live || exit 1

# Use gunicorn with uvicorn workers for production concurrency
# Cloud Run sets --workers based on MAX_CONCURRENT_REQUESTS / per-worker concurrency
CMD exec gunicorn app.main:app \
    --bind "0.0.0.0:${PORT}" \
    --workers 1 \
    --worker-class uvicorn.workers.UvicornWorker \
    --timeout 300 \
    --graceful-timeout 30 \
    --keep-alive 5 \
    --max-requests 1000 \
    --max-requests-jitter 100 \
    --access-logfile - \
    --error-logfile - \
    --log-level info
