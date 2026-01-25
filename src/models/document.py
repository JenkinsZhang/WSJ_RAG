"""
Document domain models for WSJ RAG system.

This module defines the core data structures used throughout the application
for representing news articles, text chunks, and search results.

Design Principles:
    - Immutable data classes for thread safety
    - Clear separation between raw articles and processed documents
    - Type hints for IDE support and runtime validation
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import hashlib

from src.utils.url import normalize_url


@dataclass(frozen=True)
class NewsArticle:
    """
    Represents a raw news article before processing.

    This is the input format expected from crawlers. Articles are
    transformed into ProcessedDocument after embedding and summarization.

    Attributes:
        title: Article headline
        content: Full article body text
        url: Original article URL (used as unique identifier)
        source: News source identifier (e.g., "WSJ", "Reuters")
        category: Article category (e.g., "Markets", "Tech", "Politics")
        author: Article author name(s)
        published_at: Publication timestamp
        summary: Original summary/excerpt if provided by source

    Example:
        >>> article = NewsArticle(
        ...     title="Fed Holds Rates Steady",
        ...     content="The Federal Reserve announced...",
        ...     url="https://wsj.com/articles/fed-rates-2024",
        ...     source="WSJ",
        ...     category="Markets",
        ... )
    """
    title: str
    content: str
    url: str
    source: str = "WSJ"
    category: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None
    summary: Optional[str] = None
    subtitle: Optional[str] = None
    is_exclusive: bool = False

    def generate_id(self) -> str:
        """
        Generate a unique article ID from the normalized URL.

        Returns:
            str: MD5 hash of the normalized URL as hexadecimal string

        Note:
            URL is normalized (query params removed) before hashing
            to ensure the same article always gets the same ID.
        """
        clean_url = normalize_url(self.url)
        return hashlib.md5(clean_url.encode()).hexdigest()


@dataclass
class ProcessedChunk:
    """
    Represents a processed text chunk with embedding and summary.

    Each chunk is a segment of the original article content,
    enriched with vector embeddings for semantic search.

    Attributes:
        chunk_index: Zero-based position in the original document
        content: Raw text content of this chunk
        embedding: Vector representation (4096-dim for qwen3-embedding-8b)
        chunk_summary: LLM-generated summary of this chunk

    Note:
        The embedding list is mutable for memory efficiency when
        processing large batches. Use with caution in concurrent code.
    """
    chunk_index: int
    content: str
    embedding: list[float] = field(default_factory=list)
    chunk_summary: str = ""

    def __post_init__(self) -> None:
        """Validate chunk data after initialization."""
        if self.chunk_index < 0:
            raise ValueError(f"chunk_index must be non-negative, got {self.chunk_index}")
        if not self.content or not self.content.strip():
            raise ValueError("Chunk content cannot be empty")


@dataclass
class ProcessedDocument:
    """
    Represents a fully processed document ready for indexing.

    A ProcessedDocument contains all the information needed to index
    an article into OpenSearch, including embeddings and summaries.

    Attributes:
        title: Article headline
        url: Original article URL
        article_summary: LLM-generated summary of the entire article
        chunks: List of processed chunks with embeddings
        source: News source identifier
        category: Article category
        author: Article author name(s)
        published_at: Publication timestamp (ISO format string)

    Usage:
        >>> from src.services import EmbeddingService, LLMService
        >>> embedding_svc = EmbeddingService()
        >>> llm_svc = LLMService()
        >>> doc = embedding_svc.process_document(article, llm_svc)
        >>> print(f"Processed {len(doc.chunks)} chunks")
    """
    title: str
    url: str
    article_summary: str = ""
    chunks: list[ProcessedChunk] = field(default_factory=list)
    source: str = "WSJ"
    category: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    subtitle: Optional[str] = None
    is_exclusive: bool = False

    def generate_id(self) -> str:
        """Generate a unique article ID from the normalized URL."""
        clean_url = normalize_url(self.url)
        return hashlib.md5(clean_url.encode()).hexdigest()

    @property
    def chunk_count(self) -> int:
        """Return the number of chunks in this document."""
        return len(self.chunks)

    @property
    def total_content_length(self) -> int:
        """Return the total character count across all chunks."""
        return sum(len(chunk.content) for chunk in self.chunks)


@dataclass(frozen=True)
class SearchResult:
    """
    Represents a single search result from OpenSearch.

    Encapsulates the document data and search relevance score
    returned from vector or hybrid search queries.

    Attributes:
        article_id: Unique article identifier
        chunk_id: Unique chunk identifier
        chunk_index: Position of this chunk in the original article
        title: Article headline
        content: Chunk text content
        article_summary: Full article summary
        chunk_summary: This chunk's summary
        url: Original article URL
        source: News source
        category: Article category
        score: Search relevance score (higher is better)
        published_at: Publication timestamp

    Note:
        SearchResult is immutable (frozen=True) to ensure results
        remain consistent after being returned from search operations.
    """
    article_id: str
    chunk_id: str
    chunk_index: int
    title: str
    content: str
    article_summary: str
    chunk_summary: str
    url: str
    source: str
    score: float
    category: Optional[str] = None
    published_at: Optional[str] = None

    @classmethod
    def from_opensearch_hit(cls, hit: dict) -> SearchResult:
        """
        Factory method to create SearchResult from OpenSearch response.

        Args:
            hit: Single hit from OpenSearch search response

        Returns:
            SearchResult: Populated search result object

        Example:
            >>> results = [SearchResult.from_opensearch_hit(h) for h in hits]
        """
        source = hit["_source"]
        return cls(
            article_id=source.get("article_id", ""),
            chunk_id=source.get("chunk_id", ""),
            chunk_index=source.get("chunk_index", 0),
            title=source.get("title", ""),
            content=source.get("content", ""),
            article_summary=source.get("article_summary", ""),
            chunk_summary=source.get("chunk_summary", ""),
            url=source.get("url", ""),
            source=source.get("source", ""),
            category=source.get("category"),
            score=hit.get("_score", 0.0),
            published_at=source.get("published_at"),
        )
