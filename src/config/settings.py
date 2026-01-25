"""
Centralized configuration settings for WSJ RAG system.

This module provides a single source of truth for all configuration values,
supporting both default values and environment variable overrides.

Usage:
    from src.config import get_settings

    settings = get_settings()
    print(settings.opensearch.host)
    print(settings.embedding.model)

Environment Variables:
    OPENSEARCH_HOST: OpenSearch server host (default: localhost)
    OPENSEARCH_PORT: OpenSearch server port (default: 9200)
    EMBEDDING_BASE_URL: LM Studio base URL (default: http://127.0.0.1:1234/v1)
    EMBEDDING_MODEL: Embedding model name (default: text-embedding-qwen3-embedding-8b)
    AWS_REGION: AWS region for Bedrock (default: us-east-1)
    BEDROCK_MODEL_ID: Bedrock model ID (default: global.anthropic.claude-sonnet-4-5-20250929-v1:0)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Optional


@dataclass(frozen=True)
class OpenSearchSettings:
    """
    OpenSearch connection and index configuration.

    Attributes:
        host: OpenSearch server hostname
        port: OpenSearch server port
        index_name: Name of the news index
        vector_dimension: Dimension of embedding vectors
        use_ssl: Whether to use SSL connection
        verify_certs: Whether to verify SSL certificates
    """
    host: str = "localhost"
    port: int = 9200
    index_name: str = "wsj_news"
    vector_dimension: int = 4096
    use_ssl: bool = False
    verify_certs: bool = False

    # HNSW index parameters
    hnsw_ef_construction: int = 128
    hnsw_m: int = 16
    ef_search: int = 100


@dataclass(frozen=True)
class EmbeddingSettings:
    """
    Embedding service configuration.

    Attributes:
        base_url: LM Studio API base URL
        model: Name of the embedding model
        dimension: Output vector dimension
        max_retries: Maximum retry attempts for failed requests
        retry_delay: Base delay between retries (seconds)
        timeout: Request timeout (seconds)
        chunk_size: Target chunk size in tokens
        chunk_overlap: Overlap between chunks in tokens
    """
    base_url: str = "http://127.0.0.1:1234/v1"
    model: str = "text-embedding-qwen3-embedding-8b"
    dimension: int = 4096
    max_retries: int = 3
    retry_delay: float = 1.0
    timeout: int = 60
    chunk_size: int = 512
    chunk_overlap: int = 50


@dataclass(frozen=True)
class LLMSettings:
    """
    LLM service configuration for AWS Bedrock.

    Attributes:
        region_name: AWS region for Bedrock service
        model_id: Bedrock model identifier
        max_tokens: Maximum tokens for generation
        temperature: Sampling temperature (0-1)
        max_workers: Maximum parallel workers for batch operations
    """
    region_name: str = "us-east-1"
    model_id: str = "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
    max_tokens: int = 512
    temperature: float = 0.3
    max_workers: int = 5


@dataclass(frozen=True)
class Settings:
    """
    Root configuration container for all subsystem settings.

    This class aggregates all configuration settings and provides
    a convenient way to access them throughout the application.

    Attributes:
        opensearch: OpenSearch connection settings
        embedding: Embedding service settings
        llm: LLM service settings
        debug: Enable debug mode
    """
    opensearch: OpenSearchSettings = field(default_factory=OpenSearchSettings)
    embedding: EmbeddingSettings = field(default_factory=EmbeddingSettings)
    llm: LLMSettings = field(default_factory=LLMSettings)
    debug: bool = False


def _load_from_env() -> Settings:
    """
    Load configuration from environment variables.

    Reads environment variables and constructs a Settings object
    with values overridden from the environment where specified.

    Returns:
        Settings: Configured settings instance
    """
    opensearch = OpenSearchSettings(
        host=os.getenv("OPENSEARCH_HOST", "localhost"),
        port=int(os.getenv("OPENSEARCH_PORT", "9200")),
        index_name=os.getenv("OPENSEARCH_INDEX", "wsj_news"),
        vector_dimension=int(os.getenv("VECTOR_DIMENSION", "4096")),
    )

    embedding = EmbeddingSettings(
        base_url=os.getenv("EMBEDDING_BASE_URL", "http://127.0.0.1:1234/v1"),
        model=os.getenv("EMBEDDING_MODEL", "text-embedding-qwen3-embedding-8b"),
        dimension=int(os.getenv("VECTOR_DIMENSION", "4096")),
        chunk_size=int(os.getenv("CHUNK_SIZE", "512")),
        chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "50")),
    )

    llm = LLMSettings(
        region_name=os.getenv("AWS_REGION", "us-east-1"),
        model_id=os.getenv("BEDROCK_MODEL_ID", "anthropic.claude-3-haiku-20240307-v1:0"),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "512")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
        max_workers=int(os.getenv("LLM_MAX_WORKERS", "5")),
    )

    return Settings(
        opensearch=opensearch,
        embedding=embedding,
        llm=llm,
        debug=os.getenv("DEBUG", "false").lower() == "true",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Get the singleton settings instance.

    This function is cached to ensure only one Settings instance
    is created throughout the application lifecycle.

    Returns:
        Settings: The application settings singleton

    Example:
        >>> settings = get_settings()
        >>> print(settings.opensearch.host)
        'localhost'
    """
    return _load_from_env()
