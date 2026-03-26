"""Tests for PDF processing logic."""
import io
import pytest

# Set required env vars before importing
import os
os.environ.setdefault("GCP_PROJECT_ID", "test-project")
os.environ.setdefault("GCS_BUCKET_NAME", "test-bucket")
os.environ.setdefault("CHROMA_SYNC_TO_GCS", "false")
os.environ.setdefault("ENVIRONMENT", "local")


def make_minimal_pdf() -> bytes:
    """Create a minimal valid PDF in memory using PyMuPDF."""
    import fitz
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((50, 100), "This is test page 1 content for RAG testing.")
    for i in range(2, 6):
        p = doc.new_page()
        p.insert_text((50, 100), f"Page {i} content. " * 50)  # ~250 words per page
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.mark.asyncio
async def test_process_small_pdf():
    from app.services.pdf_processor import get_pdf_processor

    pdf_bytes = make_minimal_pdf()
    processor = get_pdf_processor()

    result = await processor.process_pdf(pdf_bytes, "doc-001", "test.pdf")

    assert result.document_id == "doc-001"
    assert result.filename == "test.pdf"
    assert result.total_pages == 5
    assert result.total_chunks > 0
    assert result.processing_time_seconds > 0
    assert all(c.document_id == "doc-001" for c in result.chunks)
    assert all(c.text.strip() for c in result.chunks)


@pytest.mark.asyncio
async def test_validate_pdf_size_limit():
    from app.services.pdf_processor import get_pdf_processor
    from app.core.config import get_settings

    processor = get_pdf_processor()
    # Create bytes exceeding the limit
    oversized = b"%PDF-1.4" + b"x" * (get_settings().pdf_max_bytes + 1)
    valid, msg = processor.validate_pdf(oversized, "big.pdf")
    assert not valid
    assert "exceeds" in msg.lower()


def test_validate_invalid_pdf():
    from app.services.pdf_processor import get_pdf_processor

    processor = get_pdf_processor()
    valid, msg = processor.validate_pdf(b"not a pdf at all", "bad.pdf")
    assert not valid
