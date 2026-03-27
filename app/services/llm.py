"""
Vertex AI Gemini LLM service for generating RAG answers.
Builds a context-aware prompt from retrieved chunks and calls Gemini.
"""
import time
from typing import Optional

from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig, Part

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.metrics import (
    LLM_REQUESTS_TOTAL,
    LLM_DURATION_SECONDS,
    LLM_INPUT_TOKENS_TOTAL,
    LLM_OUTPUT_TOKENS_TOTAL,
)

logger = get_logger(__name__)

RAG_SYSTEM_PROMPT = """You are a helpful assistant that answers questions based strictly on the provided document context.

Rules:
- Answer ONLY based on the provided context.
- If the context does not contain enough information to answer the question, say so clearly.
- Cite the source document and page number when possible.
- Be concise and factual.
- Do not make up information or use knowledge outside the provided context.
"""

RAG_PROMPT_TEMPLATE = """Context from documents:
{context}

---
Question: {question}

Answer based only on the context above:"""


class LLMService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._model: Optional[GenerativeModel] = None

    @property
    def model(self) -> GenerativeModel:
        if self._model is None:
            vertexai.init(
                project=self.settings.GCP_PROJECT_ID,
                location=self.settings.VERTEX_AI_LOCATION,
            )
            self._model = GenerativeModel(
                model_name=self.settings.LLM_MODEL,
                system_instruction=RAG_SYSTEM_PROMPT,
            )
            logger.info("llm_model_loaded", model=self.settings.LLM_MODEL)
        return self._model

    def _build_context(self, chunks: list[dict]) -> str:
        """Format retrieved chunks into a numbered context block."""
        context_parts = []
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.get("metadata", {})
            filename = meta.get("filename", "unknown")
            page = meta.get("page_number", "?")
            text = chunk.get("text", "")
            context_parts.append(
                f"[{i}] Source: {filename}, Page {page}\n{text}"
            )
        return "\n\n".join(context_parts)

    def _count_tokens_estimate(self, text: str) -> int:
        """Rough token estimate: 1 token ≈ 4 characters (English text)."""
        return len(text) // 4

    def _truncate_context(self, chunks: list[dict], max_tokens: int) -> list[dict]:
        """Remove chunks from the end until context fits within max_tokens."""
        selected = []
        token_count = 0
        for chunk in chunks:
            chunk_tokens = self._count_tokens_estimate(chunk.get("text", ""))
            if token_count + chunk_tokens > max_tokens:
                break
            selected.append(chunk)
            token_count += chunk_tokens
        return selected

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def _call_gemini(self, prompt: str) -> tuple[str, int, int]:
        """Call Gemini and return (answer_text, input_tokens, output_tokens)."""
        generation_config = GenerationConfig(
            temperature=self.settings.LLM_TEMPERATURE,
            max_output_tokens=self.settings.LLM_MAX_TOKENS,
            top_p=0.95,
        )
        response = self.model.generate_content(
            prompt,
            generation_config=generation_config,
        )
        answer = response.text
        # Extract token usage if available
        input_tokens = 0
        output_tokens = 0
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
            output_tokens = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
        return answer, input_tokens, output_tokens

    async def generate_answer(
        self,
        question: str,
        retrieved_chunks: list[dict],
    ) -> tuple[str, list[dict]]:
        """
        Generate a RAG answer from the question and retrieved chunks.
        Returns (answer_text, used_chunks).
        """
        if not retrieved_chunks:
            return (
                "I could not find any relevant information in the documents to answer your question.",
                [],
            )

        # Truncate context to fit within LLM context window
        max_context_tokens = self.settings.RAG_MAX_CONTEXT_TOKENS
        used_chunks = self._truncate_context(retrieved_chunks, max_context_tokens)

        context = self._build_context(used_chunks)
        prompt = RAG_PROMPT_TEMPLATE.format(context=context, question=question)

        input_estimate = self._count_tokens_estimate(prompt)
        logger.debug(
            "llm_call_starting",
            model=self.settings.LLM_MODEL,
            chunks_used=len(used_chunks),
            estimated_input_tokens=input_estimate,
        )

        t0 = time.monotonic()
        try:
            answer, input_tokens, output_tokens = self._call_gemini(prompt)
            elapsed = time.monotonic() - t0

            LLM_REQUESTS_TOTAL.labels(status="success", model=self.settings.LLM_MODEL).inc()
            LLM_DURATION_SECONDS.observe(elapsed)
            LLM_INPUT_TOKENS_TOTAL.inc(input_tokens or input_estimate)
            LLM_OUTPUT_TOKENS_TOTAL.inc(output_tokens)

            logger.info(
                "llm_call_completed",
                model=self.settings.LLM_MODEL,
                duration_seconds=round(elapsed, 2),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
            return answer, used_chunks

        except Exception as e:
            LLM_REQUESTS_TOTAL.labels(status="failure", model=self.settings.LLM_MODEL).inc()
            logger.error("llm_call_failed", error=str(e), model=self.settings.LLM_MODEL)
            raise


_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service
