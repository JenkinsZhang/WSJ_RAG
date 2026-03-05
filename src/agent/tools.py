"""
News query tools for LlamaIndex agent.

Provides sophisticated news search capabilities including:
    - Semantic search using vector embeddings
    - Hybrid search (semantic + keyword)
    - Time-based filtering
    - Category and exclusive filtering
    - Intelligent query analysis (translation, intent detection)
    - Automatic result summarization
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.llm import LLMService, get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.progress import (
    emit_progress, emit_analyzing, emit_embedding,
    emit_searching, emit_summarizing, emit_processing
)

logger = logging.getLogger(__name__)


# ===== Query Analysis =====

QUERY_ANALYSIS_PROMPT = """You are a query analyzer for a WSJ news search system. Analyze the user's query and extract structured information.

Current date and time: {current_time}

User query: {query}

Analyze the query and output a JSON object with the following fields:
- search_query: The query translated to English, optimized for search. Add date context if the query mentions "recent", "latest", "today", etc.
- mode: One of "hybrid" (default, best for most queries), "semantic" (for conceptual questions), or "recent" (for time-based retrieval)
- exclusive_only: true if user specifically asks for exclusive/独家 news, false otherwise
- needs_summary: true if user asks to summarize/总结/概括 the results, false otherwise
- category: One of [home, world, china, tech, finance, business, politics, economy] if mentioned, null otherwise
- hours_ago: Number of hours to look back if time is mentioned (e.g., "today"=24, "this week"=168), null otherwise

Output ONLY valid JSON, no other text.

Examples:
Query: "帮我总结一下最近的独家科技新闻"
{{"search_query": "technology news January 2026", "mode": "recent", "exclusive_only": true, "needs_summary": true, "category": "tech", "hours_ago": 72}}

Query: "What's happening with Tesla stock?"
{{"search_query": "Tesla stock price market performance January 2026", "mode": "hybrid", "exclusive_only": false, "needs_summary": false, "category": "finance", "hours_ago": null}}

Query: "给我看看今天的独家新闻"
{{"search_query": "exclusive news today January 25 2026", "mode": "recent", "exclusive_only": true, "needs_summary": false, "category": null, "hours_ago": 24}}

Query: "AI对就业市场的影响"
{{"search_query": "artificial intelligence AI impact on employment job market labor", "mode": "semantic", "exclusive_only": false, "needs_summary": false, "category": null, "hours_ago": null}}
"""

SUMMARY_PROMPT = """请根据以下新闻文章内容，用中文给出一个简洁的综合总结。总结应该：
1. 概括主要事件和关键信息
2. 提及涉及的主要人物/公司/组织
3. 简要说明影响或意义

新闻内容：
{content}

请用3-5句话总结以上新闻的核心内容："""

EVALUATION_PROMPT = """Evaluate how relevant the search results are to the user's original query.

User query: {query}
Search mode used: {mode}
Result titles:
{titles}

Rate relevance 1-5 (5=highly relevant, 3=somewhat, 1=irrelevant).
Respond with ONLY a JSON object like this example:
{{"score": 4, "reason": "结果与查询高度相关", "suggested_mode": null}}"""


@dataclass
class SearchEvaluation:
    """Result of self-evaluation on search quality."""
    score: int
    reason: str
    suggested_mode: Optional[str] = None

    @classmethod
    def from_json(cls, text: str) -> "SearchEvaluation":
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0]
        # Try to extract JSON object from response
        import re
        json_match = re.search(r'\{[^}]+\}', text)
        if json_match:
            text = json_match.group()
        try:
            data = json.loads(text)
            return cls(
                score=max(1, min(5, int(data.get("score", 3)))),
                reason=data.get("reason", ""),
                suggested_mode=data.get("suggested_mode"),
            )
        except (json.JSONDecodeError, ValueError):
            logger.warning(f"Failed to parse evaluation JSON: {text[:200]}")
            return cls(score=3, reason="评估解析失败")


@dataclass
class QueryIntent:
    """Structured intent extracted from user query."""

    search_query: str
    mode: str = "hybrid"
    exclusive_only: bool = False
    needs_summary: bool = False
    category: Optional[str] = None
    hours_ago: Optional[int] = None

    @classmethod
    def from_dict(cls, data: dict) -> "QueryIntent":
        """Create QueryIntent from dictionary."""
        return cls(
            search_query=data.get("search_query", ""),
            mode=data.get("mode", "hybrid"),
            exclusive_only=data.get("exclusive_only", False),
            needs_summary=data.get("needs_summary", False),
            category=data.get("category"),
            hours_ago=data.get("hours_ago"),
        )


class QueryAnalyzer:
    """
    Analyzes user queries to extract structured intent.

    Handles:
        - Translation from any language to English
        - Search mode detection
        - Exclusive news detection
        - Summary request detection
        - Category and time range extraction
    """

    def __init__(self, llm_service: Optional[LLMService] = None) -> None:
        """Initialize the query analyzer."""
        self._llm_service = llm_service

    @property
    def llm_service(self) -> LLMService:
        """Lazy initialization of LLM service."""
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    def analyze(self, query: str) -> QueryIntent:
        """
        Analyze a query and extract structured intent.

        Args:
            query: Original user query (any language)

        Returns:
            QueryIntent with extracted information
        """
        if not query or not query.strip():
            return QueryIntent(search_query=query)

        emit_analyzing("分析查询意图...", f"原始查询: {query[:100]}")

        current_time = datetime.now().strftime("%B %d, %Y %H:%M")
        prompt = QUERY_ANALYSIS_PROMPT.format(
            current_time=current_time,
            query=query,
        )

        try:
            emit_analyzing("调用 LLM 解析意图...", None)
            response = self.llm_service.generate(prompt, max_tokens=200, temperature=0.1)

            # Parse JSON response
            # Handle potential markdown code blocks
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1]
                response = response.rsplit("```", 1)[0]

            intent_data = json.loads(response)
            intent = QueryIntent.from_dict(intent_data)

            emit_analyzing(
                "意图解析完成",
                f"搜索词: {intent.search_query[:50]}, 模式: {intent.mode}, "
                f"独家: {intent.exclusive_only}, 需要总结: {intent.needs_summary}"
            )

            logger.info(
                f"Query analyzed: '{query[:50]}' -> "
                f"mode={intent.mode}, exclusive={intent.exclusive_only}, "
                f"summary={intent.needs_summary}, category={intent.category}"
            )
            return intent

        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse query analysis JSON: {e}, using defaults")
            emit_analyzing("意图解析失败，使用默认设置", str(e))
            return QueryIntent(search_query=query)
        except Exception as e:
            logger.warning(f"Query analysis failed: {e}, using defaults")
            emit_analyzing("意图解析失败，使用默认设置", str(e))
            return QueryIntent(search_query=query)

    def summarize_results(self, results: list["NewsQueryResult"]) -> str:
        """
        Generate a summary of search results.

        Args:
            results: List of news query results

        Returns:
            Chinese summary of the results
        """
        if not results:
            return "没有找到相关新闻。"

        emit_summarizing("准备生成新闻总结...", f"共 {len(results)} 篇文章")

        # Combine content from results
        content_parts = []
        for i, r in enumerate(results, 1):
            content_parts.append(f"[{i}] {r.title}")
            if r.summary:
                content_parts.append(f"摘要: {r.summary}")
            if r.content:
                preview = r.content[:500] if len(r.content) > 500 else r.content
                content_parts.append(f"内容: {preview}")
            content_parts.append("")

        combined_content = "\n".join(content_parts)

        prompt = SUMMARY_PROMPT.format(content=combined_content)

        try:
            emit_summarizing("调用 LLM 生成总结...", None)
            summary = self.llm_service.generate(prompt, max_tokens=1000, temperature=0.3)
            emit_summarizing("总结生成完成", summary[:100] + "..." if len(summary) > 100 else summary)
            return summary
        except Exception as e:
            logger.warning(f"Failed to generate summary: {e}")
            emit_summarizing("总结生成失败", str(e))
            return "无法生成总结。"


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
    is_exclusive: bool = False

    def to_text(self) -> str:
        """Convert to readable text format."""
        score_str = f"{self.score:.4f}" if self.score is not None else "N/A"
        content_preview = (
            self.content[:500] + "..."
            if self.content and len(self.content) > 500
            else (self.content or "N/A")
        )
        exclusive_tag = " [EXCLUSIVE]" if self.is_exclusive else ""
        parts = [
            f"Title: {self.title or 'N/A'}{exclusive_tag}",
            f"Category: {self.category or 'N/A'}",
            f"Published: {self.published_at or 'N/A'}",
            f"Summary: {self.summary or 'N/A'}",
            f"Content: {content_preview}",
            f"URL: {self.url or 'N/A'}",
            f"Relevance Score: {score_str}",
        ]
        return "\n".join(parts)


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
        - Automatic result summarization when requested

    Example:
        >>> tool = NewsQueryTool()
        >>> results = tool.query("帮我总结一下最近的独家科技新闻")
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        repository: Optional[NewsRepository] = None,
        query_analyzer: Optional[QueryAnalyzer] = None,
    ) -> None:
        """Initialize the news query tool."""
        self._embedding_service = embedding_service
        self._repository = repository
        self._query_analyzer = query_analyzer

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

    @property
    def query_analyzer(self) -> QueryAnalyzer:
        """Lazy initialization of query analyzer."""
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
        # Validate inputs
        max_results = max(1, min(20, max_results))

        emit_processing("开始处理新闻查询...", f"查询: {query[:50]}")

        # Analyze query to extract intent
        intent = self.query_analyzer.analyze(query)

        logger.info(
            f"News query: original='{query[:50]}', "
            f"search='{intent.search_query[:50]}', mode={intent.mode}, "
            f"exclusive={intent.exclusive_only}, summary={intent.needs_summary}"
        )

        try:
            # Execute search based on detected mode
            results = self._execute_search(intent, max_results)
            evaluation = self._evaluate_results(query, intent, results)

            # Retry with a different mode if quality is low
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

            # Build output
            output_parts = []

            # Add summary if requested
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

    @staticmethod
    def _deduplicate(results: list, limit: int) -> list:
        """Deduplicate search results by article_id, keeping highest score."""
        seen = {}
        for r in results:
            if r.article_id not in seen or r.score > seen[r.article_id].score:
                seen[r.article_id] = r
        return list(seen.values())[:limit]

    @staticmethod
    def _to_query_results(results: list) -> list[NewsQueryResult]:
        """Convert SearchResult objects to NewsQueryResult objects."""
        return [
            NewsQueryResult(
                title=r.title, url=r.url, content=r.content,
                summary=r.article_summary or r.chunk_summary,
                category=r.category, published_at=r.published_at,
                score=r.score, is_exclusive=r.is_exclusive,
            )
            for r in results
        ]

    def _search_semantic(
        self,
        query: str,
        category: Optional[str],
        k: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        """Perform semantic (vector) search."""
        if not query.strip():
            return []
        emit_embedding("生成查询向量...", f"文本长度: {len(query)} 字符")
        query_vector = self.embedding_service.embed_text(query)
        emit_embedding("向量生成完成", f"维度: {len(query_vector)}")
        emit_searching("执行向量搜索...", f"类别: {category or '全部'}, 独家: {exclusive_only}")
        results = self.repository.search_by_vector(
            query_vector, k=k * 2, category=category, exclusive_only=exclusive_only
        )
        return self._to_query_results(self._deduplicate(results, k))

    def _search_hybrid(
        self,
        query: str,
        category: Optional[str],
        k: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        """Perform hybrid (vector + BM25) search."""
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
        return self._to_query_results(self._deduplicate(results, k))

    def _search_recent(
        self,
        query: str,
        category: Optional[str],
        hours_ago: int,
        limit: int,
        exclusive_only: bool = False,
    ) -> list[NewsQueryResult]:
        """Get recent news, optionally filtered. Falls back to latest articles if time window is empty."""
        emit_searching(f"获取最近 {hours_ago} 小时的新闻...", f"类别: {category or '全部'}, 独家: {exclusive_only}")
        results = self.repository.get_recent_news(
            hours=hours_ago, limit=limit * 2, category=category, exclusive_only=exclusive_only
        )
        if not results:
            emit_searching("时间窗口内无结果，获取最新文章...", None)
            results = self.repository.get_latest_articles(limit=limit, category=category)
        return self._to_query_results(results[:limit])

    def _execute_search(self, intent: QueryIntent, max_results: int) -> list[NewsQueryResult]:
        """Execute search based on intent mode."""
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
        """Evaluate search result quality using LLM."""
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
