"""
Query analysis and summarization for the news agent.

Handles:
    - Translation from any language to English
    - Search mode detection
    - Exclusive news / summary request detection
    - Category and time range extraction
    - Search result summarization
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from src.clients.llm import LLMService, get_llm_service
from src.agent.models import QueryIntent, NewsQueryResult
from src.agent.progress import emit_analyzing, emit_summarizing

logger = logging.getLogger(__name__)


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
        self._llm_service = llm_service

    @property
    def llm_service(self) -> LLMService:
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

    def summarize_results(self, results: list[NewsQueryResult]) -> str:
        """Generate a summary of search results."""
        if not results:
            return "没有找到相关新闻。"

        emit_summarizing("准备生成新闻总结...", f"共 {len(results)} 篇文章")

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
