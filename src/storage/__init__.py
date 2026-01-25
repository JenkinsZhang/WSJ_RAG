"""
Storage layer for WSJ RAG system.

Provides OpenSearch integration for vector storage and search operations.

Components:
    - schema: Index mapping definitions
    - repository: High-level data access operations

Note:
    OpenSearchClient is now in src.clients.opensearch
"""

from src.storage.schema import IndexSchema

# Lazy import to avoid circular dependency
# repository imports clients.opensearch, which imports storage.schema
# If we import repository here at top-level, it causes a circular import


def get_news_repository():
    """Get NewsRepository instance (lazy import to avoid circular dependency)."""
    from src.storage.repository import NewsRepository
    return NewsRepository()


__all__ = [
    "IndexSchema",
    "get_news_repository",
]
