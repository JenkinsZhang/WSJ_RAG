"""
Storage layer for WSJ RAG system.

Provides OpenSearch integration for vector storage and search operations.

Components:
    - schema: Index mapping definitions
    - repository: High-level data access operations

Note:
    OpenSearchClient is now in src.clients.opensearch
"""

from src.storage.repository import NewsRepository
from src.storage.schema import IndexSchema

__all__ = [
    "NewsRepository",
    "IndexSchema",
]
