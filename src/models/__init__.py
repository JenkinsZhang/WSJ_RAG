"""
Data models for WSJ RAG system.

Contains domain models representing news articles, chunks, and processed documents.
"""

from src.models.document import (
    NewsArticle,
    ProcessedChunk,
    ProcessedDocument,
    SearchResult,
)

__all__ = [
    "NewsArticle",
    "ProcessedChunk",
    "ProcessedDocument",
    "SearchResult",
]
