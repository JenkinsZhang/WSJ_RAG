"""
OpenSearch index schema definitions for WSJ RAG system.

This module defines the index mapping for storing news articles with
vector embeddings. The schema is optimized for:
    - Semantic search via k-NN vectors
    - Full-text search via BM25
    - Hybrid search combining both approaches

Schema Design:
    - content_vector: HNSW index with cosine similarity for semantic search
    - content/title/summary: Analyzed text fields for keyword search
    - Metadata fields: keyword type for exact matching and aggregations
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.config import get_settings


@dataclass
class IndexSchema:
    """
    OpenSearch index schema configuration.

    Encapsulates the complete index mapping including settings,
    analyzers, and field definitions.

    Attributes:
        index_name: Name of the OpenSearch index
        vector_dimension: Dimension of embedding vectors
        settings: OpenSearch settings from configuration

    Usage:
        >>> schema = IndexSchema()
        >>> mapping = schema.to_mapping()
        >>> client.indices.create(index=schema.index_name, body=mapping)
    """
    index_name: str = None
    vector_dimension: int = None

    def __post_init__(self) -> None:
        """Initialize with settings if not provided."""
        settings = get_settings()
        if self.index_name is None:
            self.index_name = settings.opensearch.index_name
        if self.vector_dimension is None:
            self.vector_dimension = settings.opensearch.vector_dimension

    def to_mapping(self) -> dict[str, Any]:
        """
        Generate the complete OpenSearch index mapping.

        Returns:
            dict: OpenSearch-compatible index mapping with settings

        Note:
            The mapping uses HNSW algorithm with Lucene engine,
            which provides good balance of speed and recall.
        """
        settings = get_settings()

        return {
            "settings": {
                "index": {
                    "number_of_shards": 1,
                    "number_of_replicas": 0,
                    "knn": True,
                    "knn.algo_param.ef_search": settings.opensearch.ef_search,
                },
                "analysis": {
                    "analyzer": {
                        "news_analyzer": {
                            "type": "custom",
                            "tokenizer": "standard",
                            "filter": ["lowercase", "stop", "snowball"]
                        }
                    }
                }
            },
            "mappings": {
                "properties": self._get_field_mappings()
            }
        }

    def _get_field_mappings(self) -> dict[str, Any]:
        """
        Define field mappings for the index.

        Returns:
            dict: Field definitions for OpenSearch mapping
        """
        settings = get_settings()

        return {
            # ===== Identifiers =====
            "article_id": {
                "type": "keyword",
                "doc_values": True  # Enable for aggregations
            },
            "chunk_id": {
                "type": "keyword"
            },
            "chunk_index": {
                "type": "integer"
            },

            # ===== Article Metadata =====
            "title": {
                "type": "text",
                "analyzer": "news_analyzer",
                "fields": {
                    "keyword": {
                        "type": "keyword",
                        "ignore_above": 512
                    }
                }
            },
            "url": {
                "type": "keyword"
            },
            "source": {
                "type": "keyword"  # WSJ, Reuters, etc.
            },
            "category": {
                "type": "keyword"  # Markets, Tech, Politics, etc.
            },
            "author": {
                "type": "keyword"
            },
            "subtitle": {
                "type": "text",
                "analyzer": "news_analyzer"
            },
            "is_exclusive": {
                "type": "boolean"
            },
            "published_at": {
                "type": "date",
                "format": "strict_date_optional_time||epoch_millis"
            },
            "crawled_at": {
                "type": "date",
                "format": "strict_date_optional_time||epoch_millis"
            },

            # ===== Content Fields =====
            "content": {
                "type": "text",
                "analyzer": "news_analyzer"
            },
            "article_summary": {
                "type": "text",
                "analyzer": "news_analyzer"
            },
            "chunk_summary": {
                "type": "text",
                "analyzer": "news_analyzer"
            },

            # ===== Vector Field =====
            "content_vector": {
                "type": "knn_vector",
                "dimension": self.vector_dimension,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {
                        "ef_construction": settings.opensearch.hnsw_ef_construction,
                        "m": settings.opensearch.hnsw_m
                    }
                }
            }
        }


# Pre-built schema instance for convenience
DEFAULT_SCHEMA = IndexSchema()
