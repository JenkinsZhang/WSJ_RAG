"""
LLM service for AWS Bedrock Claude integration.

Provides text generation and summarization capabilities using
Claude models via AWS Bedrock. Supports both single and batch
operations with parallel processing.

Architecture:
    - Uses boto3 for Bedrock API access
    - Thread pool for parallel chunk summarization
    - Configurable read timeout for long generations
"""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig

from src.config import get_settings

logger = logging.getLogger(__name__)

# ===== Prompt Templates =====

CHUNK_SUMMARY_PROMPT = """Summarize the following news excerpt in 1-2 concise sentences. Output only the summary, nothing else.

{text}"""

ARTICLE_SUMMARY_PROMPT = """Summarize the following news article in 3-5 sentences, covering key events, entities involved, and potential implications. Output only the summary, nothing else.

Title: {title}

Content:
{content}"""

# Bedrock read timeout — long generations (8k tokens) can take 2+ minutes
_BEDROCK_READ_TIMEOUT = 300  # seconds
_BEDROCK_CONNECT_TIMEOUT = 10


class LLMService:
    """
    Service for LLM-based text generation and summarization.

    Integrates with AWS Bedrock to provide Claude-powered
    text generation, optimized for news summarization tasks.
    """

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings.llm
        self._client = None

    @property
    def client(self):
        if self._client is None:
            boto_config = BotoConfig(
                read_timeout=_BEDROCK_READ_TIMEOUT,
                connect_timeout=_BEDROCK_CONNECT_TIMEOUT,
                retries={"max_attempts": 2, "mode": "adaptive"},
            )
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._settings.region_name,
                config=boto_config,
            )
            logger.info(
                f"Bedrock client initialized: model={self._settings.model_id}, "
                f"region={self._settings.region_name}, "
                f"read_timeout={_BEDROCK_READ_TIMEOUT}s"
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
        Generate text using Claude via Bedrock.

        Args:
            prompt: Input prompt
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature (0-1)

        Returns:
            str: Generated text

        Raises:
            RuntimeError: If Bedrock API call fails
        """
        resolved_max_tokens = max_tokens or self._settings.max_tokens
        resolved_temp = temperature if temperature is not None else self._settings.temperature

        prompt_len = len(prompt)
        logger.info(
            f"LLM generate: prompt_len={prompt_len} chars, "
            f"max_tokens={resolved_max_tokens}, temp={resolved_temp}"
        )

        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": resolved_max_tokens,
            "temperature": resolved_temp,
            "messages": [
                {"role": "user", "content": prompt}
            ]
        }

        start_time = time.time()

        try:
            response = self.client.invoke_model(
                modelId=self._settings.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json"
            )

            elapsed = time.time() - start_time
            result = json.loads(response["body"].read())

            # Extract response metadata
            output_text = result["content"][0]["text"].strip()
            stop_reason = result.get("stop_reason", "unknown")
            usage = result.get("usage", {})
            input_tokens = usage.get("input_tokens", "?")
            output_tokens = usage.get("output_tokens", "?")

            logger.info(
                f"LLM response: {elapsed:.1f}s, "
                f"input_tokens={input_tokens}, output_tokens={output_tokens}, "
                f"stop_reason={stop_reason}, output_len={len(output_text)} chars"
            )

            if stop_reason == "max_tokens":
                logger.warning(
                    f"LLM output TRUNCATED (hit max_tokens={resolved_max_tokens}). "
                    f"Output: {output_tokens} tokens. Consider increasing max_tokens."
                )

            return output_text

        except self.client.exceptions.ThrottlingException as e:
            elapsed = time.time() - start_time
            logger.error(f"Bedrock THROTTLED after {elapsed:.1f}s: {e}")
            raise RuntimeError(f"Bedrock API throttled: {e}") from e

        except self.client.exceptions.ModelTimeoutException as e:
            elapsed = time.time() - start_time
            logger.error(f"Bedrock MODEL TIMEOUT after {elapsed:.1f}s: {e}")
            raise RuntimeError(f"Bedrock model timeout: {e}") from e

        except Exception as e:
            elapsed = time.time() - start_time
            error_type = type(e).__name__
            logger.error(
                f"Bedrock API FAILED after {elapsed:.1f}s: "
                f"[{error_type}] {e}"
            )
            raise RuntimeError(f"LLM generation failed after {elapsed:.1f}s: [{error_type}] {e}") from e

    # ===== Summarization Methods =====

    def summarize_chunk(self, text: str) -> str:
        """Generate a brief 1-2 sentence summary for a text chunk."""
        if not text or not text.strip():
            return ""

        prompt = CHUNK_SUMMARY_PROMPT.format(text=text)
        return self.generate(prompt, max_tokens=150)

    def summarize_article(self, title: str, content: str) -> str:
        """Generate a 3-5 sentence summary for a full article."""
        if not content or not content.strip():
            return ""

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
        """Summarize multiple chunks in parallel using thread pool."""
        if not chunks:
            return []

        workers = max_workers or self._settings.max_workers
        summaries = [""] * len(chunks)

        logger.info(f"Batch summarizing {len(chunks)} chunks with {workers} workers")
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
        logger.info(f"Batch summarization completed: {len(chunks)} chunks in {elapsed:.1f}s")

        return summaries

    # ===== Health Check =====

    def health_check(self) -> dict:
        """Check Bedrock service accessibility."""
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
    global _default_service
    if _default_service is None:
        _default_service = LLMService()
    return _default_service
