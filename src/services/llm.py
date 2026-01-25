"""
LLM service for AWS Bedrock Claude integration.

Provides text generation and summarization capabilities using
Claude models via AWS Bedrock. Supports both single and batch
operations with parallel processing.

Architecture:
    - Uses boto3 for Bedrock API access
    - Supports Claude 3 Haiku for cost-effective summarization
    - Thread pool for parallel chunk summarization
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import boto3

from src.config import get_settings

logger = logging.getLogger(__name__)

# ===== Prompt Templates =====

CHUNK_SUMMARY_PROMPT = """Summarize the following news excerpt in 1-2 concise sentences. Output only the summary, nothing else.

{text}"""

ARTICLE_SUMMARY_PROMPT = """Summarize the following news article in 3-5 sentences, covering key events, entities involved, and potential implications. Output only the summary, nothing else.

Title: {title}

Content:
{content}"""


class LLMService:
    """
    Service for LLM-based text generation and summarization.

    Integrates with AWS Bedrock to provide Claude-powered
    text generation, optimized for news summarization tasks.

    Attributes:
        model_id: Bedrock model identifier
        region: AWS region

    Example:
        >>> service = LLMService()
        >>> summary = service.summarize_chunk("The Fed announced...")
        >>> print(summary)
    """

    def __init__(self) -> None:
        """Initialize the LLM service with configuration."""
        settings = get_settings()
        self._settings = settings.llm
        self._client = None

    @property
    def client(self):
        """
        Lazy initialization of Bedrock client.

        Returns:
            boto3 Bedrock runtime client
        """
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._settings.region_name
            )
        return self._client

    # ===== Core Generation Methods =====

    def generate(
            self,
            prompt: str,
            max_tokens: Optional[int] = None,
            temperature: Optional[float] = None,
    ) -> str:
        """
        Generate text using Claude.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)

        Returns:
            str: Generated text

        Raises:
            RuntimeError: If Bedrock API call fails
        """
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens or self._settings.max_tokens,
            "temperature": temperature if temperature is not None else self._settings.temperature,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        try:
            response = self.client.invoke_model(
                modelId=self._settings.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json"
            )

            result = json.loads(response["body"].read())
            return result["content"][0]["text"].strip()

        except Exception as e:
            logger.error(f"Bedrock API call failed: {e}")
            raise RuntimeError(f"LLM generation failed: {e}") from e

    # ===== Summarization Methods =====

    def summarize_chunk(self, text: str) -> str:
        """
        Generate a brief summary for a text chunk.

        Produces a 1-2 sentence summary capturing the key points.

        Args:
            text: Chunk text to summarize

        Returns:
            str: Brief summary
        """
        if not text or not text.strip():
            return ""

        prompt = CHUNK_SUMMARY_PROMPT.format(text=text)
        return self.generate(prompt, max_tokens=150)

    def summarize_article(self, title: str, content: str) -> str:
        """
        Generate a comprehensive summary for a full article.

        Produces a 3-5 sentence summary covering key events,
        entities, and implications.

        Args:
            title: Article headline
            content: Full article content

        Returns:
            str: Article summary
        """
        if not content or not content.strip():
            return ""

        # Truncate if too long (respect context limits)
        max_content_len = 15000
        if len(content) > max_content_len:
            content = content[:max_content_len] + "..."
            logger.debug("Truncated article content for summarization")

        prompt = ARTICLE_SUMMARY_PROMPT.format(title=title, content=content)
        return self.generate(prompt, max_tokens=300)

    def summarize_chunks_batch(
            self,
            chunks: list[str],
            max_workers: Optional[int] = None,
    ) -> list[str]:
        """
        Summarize multiple chunks in parallel.

        Uses thread pool for concurrent API calls to improve
        throughput when processing documents with many chunks.

        Args:
            chunks: List of chunk texts
            max_workers: Maximum parallel workers

        Returns:
            list[str]: Summaries in same order as input chunks

        Note:
            Failed chunks return empty strings rather than raising.
        """
        if not chunks:
            return []

        workers = max_workers or self._settings.max_workers
        summaries = [""] * len(chunks)

        logger.debug(f"Summarizing {len(chunks)} chunks with {workers} workers")
        start_time = time.time()

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_idx = {
                executor.submit(self.summarize_chunk, chunk): idx
                for idx, chunk in enumerate(chunks)
            }

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    summaries[idx] = future.result()
                except Exception as e:
                    logger.warning(f"Failed to summarize chunk {idx}: {e}")
                    summaries[idx] = ""

        elapsed = time.time() - start_time
        logger.debug(f"Batch summarization completed in {elapsed:.2f}s")

        return summaries

    # ===== Health Check =====

    def health_check(self) -> dict:
        """
        Check Bedrock service accessibility.

        Performs a minimal test call to verify credentials
        and model availability.

        Returns:
            dict: Health status with model info
        """
        try:
            response = self.generate("Say 'OK' in one word.", max_tokens=10)
            return {
                "status": "healthy",
                "model_id": self._settings.model_id,
                "region": self._settings.region_name,
                "test_response": response,
            }
        except Exception as e:
            logger.error(f"LLM health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
                "model_id": self._settings.model_id,
                "region": self._settings.region_name,
            }


# ===== Module-level singleton =====

_default_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """
    Get the singleton LLM service instance.

    Returns:
        LLMService: Shared service instance
    """
    global _default_service
    if _default_service is None:
        _default_service = LLMService()
    return _default_service
