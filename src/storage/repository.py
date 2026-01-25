"""
News document repository for OpenSearch operations.

Implements the Repository pattern for clean separation between
domain logic and data access. Provides high-level operations for:
    - Indexing processed documents
    - Vector similarity search
    - Hybrid search (vector + BM25)
    - Time-based queries
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional
import hashlib

from src.config import get_settings
from src.models import ProcessedDocument, ProcessedChunk, SearchResult
from src.storage.client import OpenSearchClient, get_opensearch_client

logger = logging.getLogger(__name__)


class NewsRepository:
    """
    Repository for news document storage and retrieval.

    Provides a high-level interface for CRUD operations on news
    articles stored in OpenSearch with vector embeddings.

    Attributes:
        os_client: OpenSearch client wrapper

    Example:
        >>> repo = NewsRepository()
        >>> repo.index_document(processed_doc)
        >>> results = repo.search_by_vector(query_vector, k=5)
    """

    def __init__(self, os_client: Optional[OpenSearchClient] = None) -> None:
        """
        Initialize the repository.

        Args:
            os_client: Optional OpenSearch client (uses singleton if not provided)
        """
        self.os_client = os_client or get_opensearch_client()

    @property
    def _client(self):
        """Get the underlying OpenSearch client."""
        return self.os_client.client

    @property
    def _index_name(self) -> str:
        """Get the configured index name."""
        return self.os_client.schema.index_name

    # ===== Indexing Operations =====

    def index_document(self, doc: ProcessedDocument) -> list[dict]:
        """
        Index a processed document with all its chunks.

        Each chunk is indexed as a separate document in OpenSearch,
        sharing the article-level metadata.

        Args:
            doc: Fully processed document with embeddings

        Returns:
            list[dict]: Index response for each chunk

        Example:
            >>> responses = repo.index_document(processed_doc)
            >>> print(f"Indexed {len(responses)} chunks")
        """
        article_id = doc.generate_id()
        responses = []

        for chunk in doc.chunks:
            chunk_id = f"{article_id}_{chunk.chunk_index}"

            body = {
                "article_id": article_id,
                "chunk_id": chunk_id,
                "chunk_index": chunk.chunk_index,
                "title": doc.title,
                "url": doc.url,
                "source": doc.source,
                "category": doc.category,
                "author": doc.author,
                "subtitle": doc.subtitle,
                "is_exclusive": doc.is_exclusive,
                "published_at": doc.published_at,
                "crawled_at": datetime.utcnow().isoformat(),
                "content": chunk.content,
                "article_summary": doc.article_summary,
                "chunk_summary": chunk.chunk_summary,
                "content_vector": chunk.embedding,
            }

            response = self._client.index(
                index=self._index_name,
                id=chunk_id,
                body=body,
                refresh=False,
            )
            responses.append(response)

        # Refresh once after all chunks
        self.os_client.refresh()
        logger.info(f"Indexed document '{doc.title}' with {len(responses)} chunks")

        return responses

    def bulk_index(self, documents: list[ProcessedDocument]) -> dict:
        """
        Bulk index multiple documents efficiently.

        Args:
            documents: List of processed documents

        Returns:
            dict: Summary of bulk operation results
        """
        total_chunks = 0
        errors = []

        for doc in documents:
            try:
                responses = self.index_document(doc)
                total_chunks += len(responses)
            except Exception as e:
                logger.error(f"Failed to index '{doc.title}': {e}")
                errors.append({"title": doc.title, "error": str(e)})

        return {
            "documents_processed": len(documents),
            "chunks_indexed": total_chunks,
            "errors": errors,
        }

    # ===== Search Operations =====

    def search_by_vector(
        self,
        query_vector: list[float],
        k: int = 5,
        min_score: float = 0.0,
    ) -> list[SearchResult]:
        """
        Semantic search using vector similarity.

        Uses k-NN to find chunks with similar embeddings.

        Args:
            query_vector: Query embedding vector
            k: Number of results to return
            min_score: Minimum similarity score threshold

        Returns:
            list[SearchResult]: Ranked search results
        """
        query = {
            "size": k,
            "query": {
                "knn": {
                    "content_vector": {
                        "vector": query_vector,
                        "k": k
                    }
                }
            },
            "_source": {"excludes": ["content_vector"]}
        }

        if min_score > 0:
            query["min_score"] = min_score

        response = self._client.search(index=self._index_name, body=query)
        return [SearchResult.from_opensearch_hit(hit) for hit in response["hits"]["hits"]]

    def hybrid_search(
        self,
        query_text: str,
        query_vector: list[float],
        k: int = 5,
        vector_boost: float = 0.7,
        text_boost: float = 0.3,
    ) -> list[SearchResult]:
        """
        Hybrid search combining vector similarity and BM25.

        Balances semantic understanding with keyword matching
        for improved search quality.

        Args:
            query_text: Text query for BM25 matching
            query_vector: Query embedding for semantic search
            k: Number of results to return
            vector_boost: Weight for vector similarity (0-1)
            text_boost: Weight for text matching (0-1)

        Returns:
            list[SearchResult]: Ranked search results

        Note:
            vector_boost + text_boost should typically equal 1.0
        """
        query = {
            "size": k,
            "query": {
                "bool": {
                    "should": [
                        {
                            "knn": {
                                "content_vector": {
                                    "vector": query_vector,
                                    "k": k,
                                    "boost": vector_boost
                                }
                            }
                        },
                        {
                            "multi_match": {
                                "query": query_text,
                                "fields": [
                                    "title^3",
                                    "content",
                                    "article_summary^2",
                                    "chunk_summary"
                                ],
                                "boost": text_boost
                            }
                        }
                    ]
                }
            },
            "_source": {"excludes": ["content_vector"]}
        }

        response = self._client.search(index=self._index_name, body=query)
        return [SearchResult.from_opensearch_hit(hit) for hit in response["hits"]["hits"]]

    def get_recent_news(
        self,
        hours: int = 24,
        limit: int = 50,
        category: Optional[str] = None,
    ) -> list[SearchResult]:
        """
        Retrieve recent news articles.

        Args:
            hours: Look back window in hours
            limit: Maximum number of results
            category: Optional category filter

        Returns:
            list[SearchResult]: Recent articles sorted by publish date
        """
        must_conditions = [
            {"range": {"published_at": {"gte": f"now-{hours}h"}}}
        ]

        if category:
            must_conditions.append({"term": {"category": category}})

        query = {
            "size": limit,
            "query": {"bool": {"must": must_conditions}},
            "sort": [{"published_at": {"order": "desc"}}],
            "_source": {"excludes": ["content_vector"]},
            # Collapse by article_id to get unique articles
            "collapse": {"field": "article_id"}
        }

        response = self._client.search(index=self._index_name, body=query)
        return [SearchResult.from_opensearch_hit(hit) for hit in response["hits"]["hits"]]

    def get_by_article_id(self, article_id: str) -> list[SearchResult]:
        """
        Retrieve all chunks for a specific article.

        Args:
            article_id: Unique article identifier

        Returns:
            list[SearchResult]: All chunks for the article, ordered by chunk_index
        """
        query = {
            "size": 100,  # Reasonable max chunks per article
            "query": {"term": {"article_id": article_id}},
            "sort": [{"chunk_index": {"order": "asc"}}],
            "_source": {"excludes": ["content_vector"]}
        }

        response = self._client.search(index=self._index_name, body=query)
        return [SearchResult.from_opensearch_hit(hit) for hit in response["hits"]["hits"]]

    def delete_by_article_id(self, article_id: str) -> dict:
        """
        Delete all chunks for a specific article.

        Args:
            article_id: Unique article identifier

        Returns:
            dict: Deletion result with count
        """
        response = self._client.delete_by_query(
            index=self._index_name,
            body={"query": {"term": {"article_id": article_id}}}
        )
        deleted = response.get("deleted", 0)
        logger.info(f"Deleted {deleted} chunks for article {article_id}")
        return {"deleted": deleted}

    def count_documents(self) -> int:
        """
        Get total document count in the index.

        Returns:
            int: Number of indexed chunks
        """
        response = self._client.count(index=self._index_name)
        return response.get("count", 0)
