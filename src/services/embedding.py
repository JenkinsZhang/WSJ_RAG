"""
Embedding service for text vectorization.

Provides integration with local LM Studio embedding models,
including document chunking and batch processing capabilities.

Architecture:
    - Uses LM Studio's OpenAI-compatible API
    - Supports qwen3-embedding-8b (4096 dimensions)
    - Integrates with LLMService for summary generation
"""

from __future__ import annotations

import logging
import time
from typing import Optional, TYPE_CHECKING

import requests

from src.config import get_settings
from src.models import NewsArticle, ProcessedDocument, ProcessedChunk
from src.utils.text import TextChunker

if TYPE_CHECKING:
    from src.services.llm import LLMService

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Service for generating text embeddings using local LM Studio.

    Handles single and batch embedding generation with automatic
    retry logic and connection management.

    Attributes:
        endpoint: LM Studio embeddings API endpoint
        model: Embedding model name
        dimension: Output vector dimension

    Example:
        >>> service = EmbeddingService()
        >>> embedding = service.embed_text("Hello, world!")
        >>> print(f"Dimension: {len(embedding)}")
        Dimension: 4096
    """

    def __init__(self) -> None:
        """Initialize the embedding service with configuration."""
        settings = get_settings()
        self._settings = settings.embedding
        self.endpoint = f"{self._settings.base_url}/embeddings"
        self.model = self._settings.model
        self.dimension = self._settings.dimension
        self._chunker = TextChunker(
            chunk_size=self._settings.chunk_size,
            chunk_overlap=self._settings.chunk_overlap,
        )

    # ===== Core Embedding Methods =====

    def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.

        Args:
            text: Input text to embed

        Returns:
            list[float]: Embedding vector

        Raises:
            ValueError: If text is empty
            RuntimeError: If embedding request fails after retries
        """
        if not text or not text.strip():
            raise ValueError("Text cannot be empty")

        payload = {"model": self.model, "input": text}
        return self._request_embeddings(payload)[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.

        More efficient than calling embed_text multiple times
        as it batches requests to the embedding service.

        Args:
            texts: List of texts to embed

        Returns:
            list[list[float]]: List of embedding vectors

        Raises:
            ValueError: If all texts are empty
            RuntimeError: If embedding request fails
        """
        if not texts:
            return []

        valid_texts = [t for t in texts if t and t.strip()]
        if not valid_texts:
            raise ValueError("All texts are empty")

        payload = {"model": self.model, "input": valid_texts}
        return self._request_embeddings(payload)

    def _request_embeddings(self, payload: dict) -> list[list[float]]:
        """
        Send embedding request with retry logic.

        Args:
            payload: Request payload with model and input

        Returns:
            list[list[float]]: Embedding vectors sorted by input order

        Raises:
            RuntimeError: After max retries exceeded
        """
        for attempt in range(self._settings.max_retries):
            try:
                response = requests.post(
                    self.endpoint,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    timeout=self._settings.timeout,
                )
                response.raise_for_status()
                data = response.json()

                # Sort by index to preserve input order
                embeddings_data = sorted(data["data"], key=lambda x: x["index"])
                return [item["embedding"] for item in embeddings_data]

            except requests.exceptions.RequestException as e:
                logger.warning(f"Embedding request failed (attempt {attempt + 1}): {e}")
                if attempt < self._settings.max_retries - 1:
                    time.sleep(self._settings.retry_delay * (attempt + 1))
                    continue
                raise RuntimeError(f"Embedding request failed after {self._settings.max_retries} attempts: {e}") from e

    # ===== Document Processing =====

    def process_document(
        self,
        article: NewsArticle,
        llm_service: Optional[LLMService] = None,
    ) -> ProcessedDocument:
        """
        Fully process a news article into an indexed document.

        Pipeline:
            1. Chunk the article content
            2. Generate embeddings for all chunks
            3. Generate article summary (if LLM provided)
            4. Generate chunk summaries (if LLM provided)

        Args:
            article: Raw news article to process
            llm_service: Optional LLM service for summarization

        Returns:
            ProcessedDocument: Ready for indexing

        Example:
            >>> from src.services import EmbeddingService, LLMService
            >>> embed_svc = EmbeddingService()
            >>> llm_svc = LLMService()
            >>> doc = embed_svc.process_document(article, llm_svc)
        """
        logger.info(f"Processing article: {article.title}")
        start_time = time.time()

        # Step 1: Chunk content
        chunks = self._chunker.chunk_text(article.content)
        if not chunks:
            raise ValueError(f"Article '{article.title}' produced no chunks")
        logger.debug(f"Created {len(chunks)} chunks")

        # Step 2: Generate embeddings
        embeddings = self.embed_batch(chunks)
        logger.debug(f"Generated embeddings for {len(embeddings)} chunks")

        # Step 3: Generate article summary
        if article.summary:
            article_summary = article.summary
        elif llm_service:
            article_summary = llm_service.summarize_article(article.title, article.content)
        else:
            article_summary = ""

        # Step 4: Generate chunk summaries
        if llm_service:
            chunk_summaries = llm_service.summarize_chunks_batch(chunks)
        else:
            chunk_summaries = [""] * len(chunks)

        # Step 5: Assemble processed chunks
        processed_chunks = [
            ProcessedChunk(
                chunk_index=i,
                content=chunk,
                embedding=embedding,
                chunk_summary=summary,
            )
            for i, (chunk, embedding, summary) in enumerate(
                zip(chunks, embeddings, chunk_summaries)
            )
        ]

        elapsed = time.time() - start_time
        logger.info(f"Processed '{article.title}' in {elapsed:.2f}s ({len(chunks)} chunks)")

        return ProcessedDocument(
            title=article.title,
            url=article.url,
            article_summary=article_summary,
            chunks=processed_chunks,
            source=article.source,
            category=article.category,
            author=article.author,
            published_at=article.published_at.isoformat() if article.published_at else None,
            subtitle=article.subtitle,
            is_exclusive=article.is_exclusive,
        )

    def process_articles_batch(
        self,
        articles: list[NewsArticle],
        llm_service: Optional[LLMService] = None,
    ) -> list[ProcessedDocument]:
        """
        Process multiple articles.

        Args:
            articles: List of articles to process
            llm_service: Optional LLM for summarization

        Returns:
            list[ProcessedDocument]: Successfully processed documents

        Note:
            Failed articles are logged but don't stop processing.
        """
        results = []
        for article in articles:
            try:
                doc = self.process_document(article, llm_service)
                results.append(doc)
            except Exception as e:
                logger.error(f"Failed to process '{article.title}': {e}")
        return results

    # ===== Health Check =====

    def health_check(self) -> dict:
        """
        Check embedding service availability.

        Returns:
            dict: Health status including model availability
        """
        try:
            response = requests.get(
                f"{self._settings.base_url}/models",
                timeout=5
            )
            response.raise_for_status()

            models = response.json().get("data", [])
            model_ids = [m["id"] for m in models]

            return {
                "status": "healthy",
                "available_models": model_ids,
                "configured_model": self.model,
                "model_available": self.model in model_ids,
            }
        except Exception as e:
            logger.error(f"Embedding service health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }


# ===== Module-level singleton =====

_default_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """
    Get the singleton embedding service instance.

    Returns:
        EmbeddingService: Shared service instance
    """
    global _default_service
    if _default_service is None:
        _default_service = EmbeddingService()
    return _default_service
