"""
Storage layer for WSJ RAG system.

Provides OpenSearch integration for vector storage and search operations.

Components:
    - schema: Index mapping definitions
    - client: OpenSearch client factory
    - repository: High-level data access operations
"""

from src.storage.client import OpenSearchClient, get_opensearch_client
from src.storage.repository import NewsRepository
from src.storage.schema import IndexSchema

__all__ = [
    "OpenSearchClient",
    "get_opensearch_client",
    "NewsRepository",
    "IndexSchema",
]
