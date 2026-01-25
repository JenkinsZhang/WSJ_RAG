"""
External service clients for WSJ RAG system.

Provides clients for:
    - OpenSearch vector database
    - Text embedding API (LM Studio)
    - LLM API (AWS Bedrock Claude)
"""

from src.clients.opensearch import OpenSearchClient, get_opensearch_client
from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.llm import LLMService, get_llm_service

__all__ = [
    "OpenSearchClient",
    "get_opensearch_client",
    "EmbeddingService",
    "get_embedding_service",
    "LLMService",
    "get_llm_service",
]
