"""
News query tool for LlamaIndex agent.

Provides sophisticated news search capabilities including:
    - Semantic search using vector embeddings
    - Hybrid search (semantic + keyword)
    - Time-based filtering
    - Category and exclusive filtering
    - Automatic result summarization
    - Self-evaluation with retry
"""

from __future__ import annotations

import logging
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.llm import get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.models import (
    QueryIntent, NewsQueryResult, SearchEvaluation,
    deduplicate_results, to_query_results,
)
from src.agent.query_analyzer import QueryAnalyzer, EVALUATION_PROMPT
from src.agent.progress import (
    emit_embedding, emit_searching, emit_processing,
)

logger = logging.getLogger(__name__)


class NewsQueryTool:
    """
    Advanced news query tool for RAG agent.

    Supports multiple search modes:
        - semantic: Pure vector similarity search
        - hybrid: Combined vector + BM25 keyword search
        - recent: Time-based retrieval with optional filters

    Features:
        - Automatic query translation (any language -> English)
        - Intent detection (exclusive news, summary requests)
        - Query rewriting with temporal context
        - Self-evaluation with automatic retry
        - Automatic result summarization when requested
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        repository: Optional[NewsRepository] = None,
        query_analyzer: Optional[QueryAnalyzer] = None,
    ) -> None:
        self._embedding_service = embedding_service
        self._repository = repository
        self._query_analyzer = query_analyzer

    @property
    def embedding_service(self) -> EmbeddingService:
        if self._embedding_service is None:
            self._embedding_service = get_embedding_service()
        return self._embedding_service

    @property
    def repository(self) -> NewsRepository:
        if self._repository is None:
            os_client = get_opensearch_client()
            self._repository = NewsRepository(os_client)
        return self._repository

    @property
    def query_analyzer(self) -> QueryAnalyzer:
        if self._query_analyzer is None:
            self._query_analyzer = QueryAnalyzer()
        return self._query_analyzer

    def query(
        self,
        query: str,
        max_results: int = 5,
    ) -> str:
        """
        Query news articles with intelligent intent detection.

        This tool automatically:
        - Translates queries from any language to English
        - Detects if user wants exclusive news only
        - Detects if user wants a summary of results
        - Chooses the best search mode based on query content
        - Adds temporal context when relevant
        - Evaluates result quality and retries with a different mode if needed

        Args:
            query: The search query or question about news (any language).
                   Can include requests like "总结", "独家", "最近" etc.
            max_results: Maximum number of results to return (1-20, default 5).

        Returns:
            A formatted string containing the search results with titles,
            summaries, content excerpts, and URLs. If summary was requested,
            includes a synthesized summary at the beginning.

        Examples:
            - query("What's happening with AI?")
            - query("帮我总结一下最近的独家科技新闻")
            - query("Trump政策最新动态", max_results=10)
        """
        max_results = max(1, min(20, max_results))

        emit_processing("开始处理新闻查询...", f"查询: {query[:50]}")

        intent = self.query_analyzer.analyze(query)

        logger.info(
            f"News query: original='{query[:50]}', "
            f"search='{intent.search_query[:50]}', mode={intent.mode}, "
            f"exclusive={intent.exclusive_only}, summary={intent.needs_summary}"
        )

        try:
            results = self._execute_search(intent, max_results)
            evaluation = self._evaluate_results(query, intent, results)

            if evaluation.score < 3 and intent.mode != "recent":
                retry_mode = "semantic" if intent.mode == "hybrid" else "hybrid"
                logger.info(
                    f"Low quality score ({evaluation.score}/5), "
                    f"retrying with {retry_mode} mode"
                )
                retry_intent = QueryIntent(
                    search_query=intent.search_query,
                    mode=retry_mode,
                    exclusive_only=intent.exclusive_only,
                    needs_summary=intent.needs_summary,
                    category=intent.category,
                    hours_ago=intent.hours_ago,
                )
                retry_results = self._execute_search(retry_intent, max_results)
                retry_evaluation = self._evaluate_results(query, retry_intent, retry_results)

                if retry_evaluation.score > evaluation.score:
                    results = retry_results
                    evaluation = retry_evaluation
                    intent = retry_intent

            emit_searching(
                f"搜索完成，找到 {len(results)} 篇文章",
                ", ".join([r.title[:30] for r in results[:3]]) + ("..." if len(results) > 3 else "") if results else None
            )

            if not results:
                emit_processing("未找到相关文章", None)
                return f"No news articles found for query: '{query}'"

            output_parts = []

            if intent.needs_summary:
                summary = self.query_analyzer.summarize_results(results)
                output_parts.append("=== 新闻总结 ===")
                output_parts.append(summary)
                output_parts.append("")
                output_parts.append("=== 详细文章 ===")

            output_parts.append(f"Found {len(results)} relevant articles (quality: {evaluation.score}/5):\n")
            for i, result in enumerate(results, 1):
                output_parts.append(f"--- Article {i} ---")
                output_parts.append(result.to_text())
                output_parts.append("")

            emit_processing("查询处理完成", f"返回 {len(results)} 篇文章")
            return "\n".join(output_parts)

        except Exception as e:
            logger.error(f"News query failed: {e}")
            emit_processing("查询处理失败", str(e))
            return f"Error searching news: {str(e)}"

    def _search_semantic(
        self,
        query: str,
        category: Optional[str],
        k: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        if not query.strip():
            return []
        emit_embedding("生成查询向量...", f"文本长度: {len(query)} 字符")
        query_vector = self.embedding_service.embed_text(query)
        emit_embedding("向量生成完成", f"维度: {len(query_vector)}")
        emit_searching("执行向量搜索...", f"类别: {category or '全部'}, 独家: {exclusive_only}")
        results = self.repository.search_by_vector(
            query_vector, k=k * 2, category=category, exclusive_only=exclusive_only
        )
        return to_query_results(deduplicate_results(results, k))

    def _search_hybrid(
        self,
        query: str,
        category: Optional[str],
        k: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        if not query.strip():
            return []
        emit_embedding("生成查询向量...", f"文本长度: {len(query)} 字符")
        query_vector = self.embedding_service.embed_text(query)
        emit_embedding("向量生成完成", f"维度: {len(query_vector)}")
        emit_searching("执行混合搜索 (向量 + BM25)...", f"类别: {category or '全部'}, 独家: {exclusive_only}")
        results = self.repository.hybrid_search(
            query_text=query, query_vector=query_vector,
            k=k * 2, vector_boost=0.6, text_boost=0.4,
            category=category, exclusive_only=exclusive_only,
        )
        return to_query_results(deduplicate_results(results, k))

    def _search_recent(
        self,
        query: str,
        category: Optional[str],
        hours_ago: int,
        limit: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        emit_searching(f"获取最近 {hours_ago} 小时的新闻...", f"类别: {category or '全部'}, 独家: {exclusive_only}")
        results = self.repository.get_recent_news(
            hours=hours_ago, limit=limit * 2, category=category, exclusive_only=exclusive_only
        )
        if not results:
            emit_searching("时间窗口内无结果，获取最新文章...", None)
            results = self.repository.get_latest_articles(limit=limit, category=category)
        return to_query_results(results[:limit])

    def _execute_search(self, intent: QueryIntent, max_results: int) -> list[NewsQueryResult]:
        mode_names = {"recent": "时间排序", "semantic": "语义搜索", "hybrid": "混合搜索"}
        emit_searching(
            f"执行{mode_names.get(intent.mode, intent.mode)}...",
            f"搜索词: {intent.search_query[:50]}"
        )
        if intent.mode == "recent":
            return self._search_recent(
                query=intent.search_query, category=intent.category,
                hours_ago=intent.hours_ago or 72, limit=max_results,
                exclusive_only=intent.exclusive_only,
            )
        elif intent.mode == "semantic":
            return self._search_semantic(
                query=intent.search_query, category=intent.category,
                k=max_results, exclusive_only=intent.exclusive_only,
            )
        else:
            return self._search_hybrid(
                query=intent.search_query, category=intent.category,
                k=max_results, exclusive_only=intent.exclusive_only,
            )

    def _evaluate_results(self, query: str, intent: QueryIntent, results: list[NewsQueryResult]) -> SearchEvaluation:
        if not results:
            return SearchEvaluation(score=1, reason="无搜索结果")

        from src.agent.progress import emit_evaluating
        emit_evaluating("评估搜索结果质量...", f"共 {len(results)} 篇文章")

        titles = "\n".join(f"- {r.title}" for r in results[:10])
        prompt = EVALUATION_PROMPT.format(query=query, mode=intent.mode, titles=titles)

        try:
            llm = get_llm_service()
            response = llm.generate(prompt, max_tokens=100, temperature=0.1)
            evaluation = SearchEvaluation.from_json(response)
            emit_evaluating(f"搜索质量: {evaluation.score}/5", evaluation.reason)
            return evaluation
        except Exception as e:
            logger.warning(f"Self-evaluation failed: {e}")
            return SearchEvaluation(score=3, reason="评估失败")


# Singleton instance
_news_query_tool: Optional[NewsQueryTool] = None


def get_news_query_tool() -> NewsQueryTool:
    global _news_query_tool
    if _news_query_tool is None:
        _news_query_tool = NewsQueryTool()
    return _news_query_tool


def create_news_query_function_tool() -> FunctionTool:
    """Create a LlamaIndex FunctionTool for news query."""
    tool = get_news_query_tool()

    return FunctionTool.from_defaults(
        fn=tool.query,
        name="news_query",
        description="""
Search and retrieve WSJ news articles with intelligent query understanding.

This tool automatically:
- Translates queries from any language (Chinese, etc.) to English for search
- Detects search intent (exclusive news, summary requests, time ranges)
- Chooses the best search strategy (hybrid/semantic/recent)
- Summarizes results when requested

Usage:
- Just describe what news you're looking for in natural language
- Include "独家" or "exclusive" to filter for exclusive articles only
- Include "总结" or "summarize" to get a synthesized summary
- Include time references like "今天", "最近", "this week" for time-based search

Parameters:
- query: Natural language query describing what news you want (any language)
- max_results: Number of articles to return (1-20, default 5)

Examples:
- query("What's happening with Tesla?")
- query("帮我总结一下最近的独家科技新闻")
- query("Trump政策最新动态", max_results=10)

Use this tool when the user wants to find or search for specific recent news articles.
Do NOT use this tool for general knowledge questions, greetings, or casual conversation.
""",
    )
