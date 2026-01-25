"""
OpenSearch client factory and connection management.

Provides a thin wrapper around the opensearch-py client with:
    - Connection pooling
    - Health check utilities
    - Index lifecycle management
"""

from __future__ import annotations

import logging
from typing import Optional

from opensearchpy import OpenSearch

from src.config import get_settings
from src.storage.schema import IndexSchema, DEFAULT_SCHEMA

logger = logging.getLogger(__name__)


class OpenSearchClient:
    """
    OpenSearch client wrapper with connection management.

    Provides convenient methods for common operations and
    ensures consistent configuration across the application.

    Attributes:
        client: Underlying opensearch-py client instance
        schema: Index schema configuration

    Example:
        >>> client = OpenSearchClient()
        >>> if client.health_check():
        ...     client.ensure_index_exists()
    """

    def __init__(
        self,
        client: Optional[OpenSearch] = None,
        schema: Optional[IndexSchema] = None,
    ) -> None:
        """
        Initialize the OpenSearch client.

        Args:
            client: Optional pre-configured OpenSearch client
            schema: Optional custom index schema
        """
        self._client = client
        self.schema = schema or DEFAULT_SCHEMA

    @property
    def client(self) -> OpenSearch:
        """
        Lazy initialization of OpenSearch client.

        Returns:
            OpenSearch: Configured client instance
        """
        if self._client is None:
            settings = get_settings()
            self._client = OpenSearch(
                hosts=[{
                    "host": settings.opensearch.host,
                    "port": settings.opensearch.port,
                }],
                http_compress=True,
                use_ssl=settings.opensearch.use_ssl,
                verify_certs=settings.opensearch.verify_certs,
                ssl_show_warn=False,
            )
        return self._client

    def health_check(self) -> dict:
        """
        Check cluster health and connectivity.

        Returns:
            dict: Health status including cluster state

        Example:
            >>> health = client.health_check()
            >>> if health["status"] == "healthy":
            ...     print(f"Cluster: {health['cluster_status']}")
        """
        try:
            cluster_health = self.client.cluster.health()
            return {
                "status": "healthy",
                "cluster_name": cluster_health.get("cluster_name"),
                "cluster_status": cluster_health.get("status"),
                "number_of_nodes": cluster_health.get("number_of_nodes"),
            }
        except Exception as e:
            logger.error(f"OpenSearch health check failed: {e}")
            return {
                "status": "unhealthy",
                "error": str(e),
            }

    def index_exists(self) -> bool:
        """
        Check if the configured index exists.

        Returns:
            bool: True if index exists
        """
        return self.client.indices.exists(index=self.schema.index_name)

    def ensure_index_exists(self, recreate: bool = False) -> dict:
        """
        Ensure the index exists, optionally recreating it.

        Args:
            recreate: If True, delete and recreate existing index

        Returns:
            dict: Operation result with status

        Warning:
            Setting recreate=True will DELETE all existing data!
        """
        index_name = self.schema.index_name

        if self.index_exists():
            if recreate:
                logger.warning(f"Deleting existing index: {index_name}")
                self.client.indices.delete(index=index_name)
            else:
                logger.info(f"Index already exists: {index_name}")
                return {"status": "exists", "index": index_name}

        # Create new index
        mapping = self.schema.to_mapping()
        response = self.client.indices.create(index=index_name, body=mapping)
        logger.info(f"Created index: {index_name}")

        return {
            "status": "created",
            "index": index_name,
            "acknowledged": response.get("acknowledged"),
        }

    def delete_index(self) -> dict:
        """
        Delete the configured index.

        Returns:
            dict: Deletion result

        Warning:
            This permanently deletes all data in the index!
        """
        if not self.index_exists():
            return {"status": "not_exists", "index": self.schema.index_name}

        self.client.indices.delete(index=self.schema.index_name)
        logger.info(f"Deleted index: {self.schema.index_name}")
        return {"status": "deleted", "index": self.schema.index_name}

    def get_index_stats(self) -> dict:
        """
        Get index statistics.

        Returns:
            dict: Index statistics including document count
        """
        if not self.index_exists():
            return {"status": "not_exists"}

        stats = self.client.indices.stats(index=self.schema.index_name)
        index_stats = stats["indices"][self.schema.index_name]["primaries"]

        return {
            "status": "ok",
            "index": self.schema.index_name,
            "doc_count": index_stats["docs"]["count"],
            "size_bytes": index_stats["store"]["size_in_bytes"],
        }

    def refresh(self) -> None:
        """
        Refresh the index to make recent changes searchable.

        Call this after bulk indexing operations.
        """
        self.client.indices.refresh(index=self.schema.index_name)


# ===== Module-level singleton =====

_default_client: Optional[OpenSearchClient] = None


def get_opensearch_client() -> OpenSearchClient:
    """
    Get the singleton OpenSearch client instance.

    Returns:
        OpenSearchClient: Shared client instance

    Example:
        >>> client = get_opensearch_client()
        >>> results = client.client.search(...)
    """
    global _default_client
    if _default_client is None:
        _default_client = OpenSearchClient()
    return _default_client
