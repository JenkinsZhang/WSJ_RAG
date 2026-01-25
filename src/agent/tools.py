"""
News query tools for LlamaIndex agent.

Provides sophisticated news search capabilities including:
    - Semantic search using vector embeddings
    - Hybrid search (semantic + keyword)
    - Time-based filtering
    - Category filtering
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    """Search mode for news query."""
    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    RECENT = "recent"


@dataclass
class NewsQueryResult:
    """Structured result from news query."""
    title: str
    url: str
    content: str
    summary: str
    category: Optional[str]
    published_at: Optional[str]
    score: float

    def to_text(self) -> str:
        """Convert to readable text format."""
        parts = [
            f"Title: {self.title}",
            f"Category: {self.category or 'N/A'}",
            f"Published: {self.published_at or 'N/A'}",
            f"Summary: {self.summary}",
            f"Content: {self.content[:500]}..." if len(self.content) > 500 else f"Content: {self.content}",
            f"URL: {self.url}",
            f"Relevance Score: {self.score:.4f}",
        ]
        return "\n".join(parts)


class NewsQueryTool:
    """
    Advanced news query tool for RAG agent.

    Supports multiple search modes:
        - semantic: Pure vector similarity search
        - hybrid: Combined vector + BM25 keyword search
        - recent: Time-based retrieval with optional filters

    Example:
        >>> tool = NewsQueryTool()
        >>> results = tool.query(
        ...     query="Federal Reserve interest rate decision",
        ...     mode="hybrid",
        ...     category="finance",
        ...     max_results=5
        ... )
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        repository: Optional[NewsRepository] = None,
    ) -> None:
        """Initialize the news query tool."""
        self._embedding_service = embedding_service
        self._repository = repository

    @property
    def embedding_service(self) -> EmbeddingService:
        """Lazy initialization of embedding service."""
        if self._embedding_service is None:
            self._embedding_service = get_embedding_service()
        return self._embedding_service

    @property
    def repository(self) -> NewsRepository:
        """Lazy initialization of repository."""
        if self._repository is None:
            os_client = get_opensearch_client()
            self._repository = NewsRepository(os_client)
        return self._repository

    def query(
        self,
        query: str,
        mode: str = "hybrid",
        category: Optional[str] = None,
        hours_ago: Optional[int] = None,
        max_results: int = 5,
    ) -> str:
        """
        Query news articles with flexible search options.

        This is the main entry point for the agent to search news.
        It supports semantic search, hybrid search, and time-based queries.

        Args:
            query: The search query or question about news.
                   For semantic/hybrid mode: describe what you're looking for.
                   For recent mode: can be empty or used as additional filter.
            mode: Search mode - one of:
                  - "semantic": Pure vector similarity search, best for conceptual queries
                  - "hybrid": Combined vector + keyword search, best for specific topics
                  - "recent": Get latest news, optionally filtered by category
            category: Filter by news category. Valid categories:
                      home, world, china, tech, finance, business, politics, economy
            hours_ago: For recent mode, limit to articles from last N hours.
                       Default is 72 hours if not specified.
            max_results: Maximum number of results to return (1-20).

        Returns:
            A formatted string containing the search results with titles,
            summaries, content excerpts, and URLs. Returns a message if
            no results found.

        Examples:
            - query("What's happening with AI regulations?", mode="hybrid")
            - query("", mode="recent", category="tech", hours_ago=24)
            - query("Federal Reserve monetary policy", mode="semantic", max_results=3)
        """
        # Validate inputs
        max_results = max(1, min(20, max_results))
        mode = mode.lower()

        if mode not in ["semantic", "hybrid", "recent"]:
            mode = "hybrid"

        logger.info(f"News query: mode={mode}, query='{query[:50]}...', category={category}")

        try:
            if mode == "recent":
                results = self._search_recent(
                    query=query,
                    category=category,
                    hours_ago=hours_ago or 72,
                    limit=max_results,
                )
            elif mode == "semantic":
                results = self._search_semantic(
                    query=query,
                    category=category,
                    k=max_results,
                )
            else:  # hybrid
                results = self._search_hybrid(
                    query=query,
                    category=category,
                    k=max_results,
                )

            if not results:
                return f"No news articles found for query: '{query}' with mode: {mode}"

            # Format results
            output_parts = [f"Found {len(results)} relevant articles:\n"]
            for i, result in enumerate(results, 1):
                output_parts.append(f"--- Article {i} ---")
                output_parts.append(result.to_text())
                output_parts.append("")

            return "\n".join(output_parts)

        except Exception as e:
            logger.error(f"News query failed: {e}")
            return f"Error searching news: {str(e)}"

    def _search_semantic(
        self,
        query: str,
        category: Optional[str],
        k: int,
    ) -> list[NewsQueryResult]:
        """Perform semantic (vector) search."""
        if not query.strip():
            return []

        # Generate query embedding
        query_vector = self.embedding_service.embed_text(query)

        # Search
        search_results = self.repository.search_by_vector(query_vector, k=k * 2)

        # Filter by category if specified
        if category:
            search_results = [r for r in search_results if r.category == category]

        # Deduplicate by article_id, keep highest score
        seen_articles = {}
        for result in search_results:
            if result.article_id not in seen_articles:
                seen_articles[result.article_id] = result
            elif result.score > seen_articles[result.article_id].score:
                seen_articles[result.article_id] = result

        unique_results = list(seen_articles.values())[:k]

        return [
            NewsQueryResult(
                title=r.title,
                url=r.url,
                content=r.content,
                summary=r.article_summary or r.chunk_summary,
                category=r.category,
                published_at=r.published_at,
                score=r.score,
            )
            for r in unique_results
        ]

    def _search_hybrid(
        self,
        query: str,
        category: Optional[str],
        k: int,
    ) -> list[NewsQueryResult]:
        """Perform hybrid (vector + BM25) search."""
        if not query.strip():
            return []

        # Generate query embedding
        query_vector = self.embedding_service.embed_text(query)

        # Hybrid search
        search_results = self.repository.hybrid_search(
            query_text=query,
            query_vector=query_vector,
            k=k * 2,
            vector_boost=0.6,
            text_boost=0.4,
        )

        # Filter by category if specified
        if category:
            search_results = [r for r in search_results if r.category == category]

        # Deduplicate by article_id
        seen_articles = {}
        for result in search_results:
            if result.article_id not in seen_articles:
                seen_articles[result.article_id] = result
            elif result.score > seen_articles[result.article_id].score:
                seen_articles[result.article_id] = result

        unique_results = list(seen_articles.values())[:k]

        return [
            NewsQueryResult(
                title=r.title,
                url=r.url,
                content=r.content,
                summary=r.article_summary or r.chunk_summary,
                category=r.category,
                published_at=r.published_at,
                score=r.score,
            )
            for r in unique_results
        ]

    def _search_recent(
        self,
        query: str,
        category: Optional[str],
        hours_ago: int,
        limit: int,
    ) -> list[NewsQueryResult]:
        """Get recent news, optionally filtered."""
        search_results = self.repository.get_recent_news(
            hours=hours_ago,
            limit=limit * 2,
            category=category,
        )

        # If query provided, re-rank by relevance
        if query.strip():
            query_vector = self.embedding_service.embed_text(query)
            # Simple re-ranking by computing similarity
            # (In production, you might use a more sophisticated approach)

        unique_results = search_results[:limit]

        return [
            NewsQueryResult(
                title=r.title,
                url=r.url,
                content=r.content,
                summary=r.article_summary or r.chunk_summary,
                category=r.category,
                published_at=r.published_at,
                score=r.score,
            )
            for r in unique_results
        ]


# Singleton instance
_news_query_tool: Optional[NewsQueryTool] = None


def get_news_query_tool() -> NewsQueryTool:
    """Get singleton news query tool instance."""
    global _news_query_tool
    if _news_query_tool is None:
        _news_query_tool = NewsQueryTool()
    return _news_query_tool


def create_news_query_function_tool() -> FunctionTool:
    """
    Create a LlamaIndex FunctionTool for news query.

    Returns:
        FunctionTool: Ready-to-use tool for LlamaIndex agent
    """
    tool = get_news_query_tool()

    return FunctionTool.from_defaults(
        fn=tool.query,
        name="news_query",
        description="""
Search and retrieve WSJ news articles. Supports three search modes:

1. "hybrid" (default): Combined semantic + keyword search. Best for specific topics.
   Example: query="Tesla earnings report", mode="hybrid"

2. "semantic": Pure vector similarity search. Best for conceptual queries.
   Example: query="impact of inflation on consumer spending", mode="semantic"

3. "recent": Get latest news by time. Best for current events.
   Example: query="", mode="recent", hours_ago=24, category="tech"

Parameters:
- query: Search query describing what news you're looking for
- mode: "semantic", "hybrid", or "recent"
- category: Optional filter (home/world/china/tech/finance/business/politics/economy)
- hours_ago: For recent mode, limit to last N hours
- max_results: Number of results (1-20, default 5)

Always use this tool when the user asks about news, current events, or wants information
that might be in recent WSJ articles.
""",
    )
