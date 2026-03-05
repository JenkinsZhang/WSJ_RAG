"""
Deep research tool for multi-angle topic analysis.

Provides comprehensive research capabilities by:
    - Generating multiple search angles for a topic using LLM
    - Executing parallel searches from different perspectives
    - Merging and deduplicating results across angles
    - Synthesizing a comprehensive Chinese research report
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.llm import LLMService, get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.models import deduplicate_results
from src.agent.progress import (
    emit_analyzing, emit_searching, emit_summarizing, emit_processing
)

logger = logging.getLogger(__name__)


# ===== Prompts =====

ANGLE_GENERATION_PROMPT = """You are a research analyst. Given a topic, generate {n} different search angles to thoroughly research it. Each angle should explore a distinct aspect of the topic.

Current date: {current_date}
Topic: {topic}

For each angle, provide:
- angle: A short Chinese name describing the perspective (e.g., "市场影响", "技术发展", "政策监管")
- query: An English search query optimized for news retrieval from that angle

Output ONLY valid JSON in this exact format, no other text:
{{"angles": [{{"angle": "...", "query": "..."}}, {{"angle": "...", "query": "..."}}]}}

Example for topic "AI发展对就业的影响":
{{"angles": [
  {{"angle": "技术进展", "query": "artificial intelligence AI latest breakthroughs technology advancement 2026"}},
  {{"angle": "就业市场冲击", "query": "AI automation impact jobs employment layoffs workforce displacement"}},
  {{"angle": "企业应用", "query": "companies adopting AI business transformation productivity gains"}},
  {{"angle": "政策与监管", "query": "AI regulation government policy workforce retraining programs"}}
]}}"""

RESEARCH_REPORT_PROMPT = """你是一位专业的新闻分析师。请根据以下从多个角度搜集的新闻文章，撰写一份关于「{topic}」的综合研究报告。

当前日期：{current_date}

搜集到的文章：
{articles}

请撰写一份结构清晰的中文研究报告，包含以下部分：

## 概述
简要介绍该主题的背景和当前态势（2-3句话）。

## 关键发现
列出最重要的发现和事实（3-5个要点），每个要点引用具体文章。

## 多角度分析
从不同角度（如经济、政治、技术、社会等）分析该主题，结合搜集到的文章进行论述。

## 影响与展望
分析该主题可能产生的影响，以及未来的发展趋势。

引用文章时使用「标题」格式（中文引号包裹文章标题）。
确保报告客观、全面、有深度，字数控制在800-1500字。"""


# ===== Default Fallback Angles =====

_DEFAULT_ANGLES = [
    {"angle": "核心动态", "query": ""},
    {"angle": "市场影响", "query": "market impact economic implications"},
    {"angle": "政策与监管", "query": "policy regulation government response"},
    {"angle": "行业趋势", "query": "industry trend outlook future development"},
]


class DeepResearchTool:
    """
    Multi-angle deep research tool for comprehensive topic analysis.

    Generates multiple search perspectives for a topic, executes searches
    from each angle, merges results, and synthesizes a comprehensive report.

    Features:
        - LLM-powered search angle generation
        - Multi-perspective article gathering
        - Cross-angle deduplication
        - Comprehensive Chinese research report synthesis

    Example:
        >>> tool = DeepResearchTool()
        >>> report = tool.deep_research("AI对就业市场的影响")
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        repository: Optional[NewsRepository] = None,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        """Initialize the deep research tool."""
        self._embedding_service = embedding_service
        self._repository = repository
        self._llm_service = llm_service

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
    def llm_service(self) -> LLMService:
        """Lazy initialization of LLM service."""
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    def deep_research(self, topic: str, max_results: int = 10) -> str:
        """
        Conduct deep research on a topic from multiple angles.

        Generates several search perspectives using LLM, searches for articles
        from each angle, merges and deduplicates results, then synthesizes
        a comprehensive research report.

        Args:
            topic: The research topic (any language). Will be analyzed to
                   generate multiple English search queries.
            max_results: Maximum total articles to include (3-20, default 10).
                        Articles are distributed across search angles.

        Returns:
            A formatted string containing:
            - Research report header with topic and article count
            - LLM-generated comprehensive analysis report
            - Reference list of all cited articles with URLs

        Examples:
            - deep_research("AI对就业市场的影响")
            - deep_research("美联储利率政策", max_results=15)
            - deep_research("Trump tariff policy impact", max_results=8)
        """
        # Validate inputs
        max_results = max(3, min(20, max_results))

        emit_processing("开始深度研究...", f"主题: {topic[:80]}")

        # Step 1: Generate search angles
        angles = self._generate_angles(topic, n=4)
        emit_analyzing(
            f"生成了 {len(angles)} 个研究角度",
            ", ".join(a["angle"] for a in angles),
        )

        # Step 2: Search from each angle
        all_results = []
        per_angle_limit = max(2, max_results // len(angles) + 1)

        for i, angle in enumerate(angles, 1):
            angle_name = angle["angle"]
            angle_query = angle["query"]

            emit_searching(
                f"搜索角度 [{i}/{len(angles)}]: {angle_name}",
                f"查询: {angle_query[:60]}",
            )

            try:
                query_vector = self.embedding_service.embed_text(angle_query)
                results = self.repository.hybrid_search(
                    query_text=angle_query,
                    query_vector=query_vector,
                    k=per_angle_limit * 2,
                    vector_boost=0.6,
                    text_boost=0.4,
                )
                deduped = deduplicate_results(results, per_angle_limit)
                all_results.extend(deduped)

                emit_searching(
                    f"角度「{angle_name}」找到 {len(deduped)} 篇文章",
                    None,
                )
            except Exception as e:
                logger.warning(f"Search failed for angle '{angle_name}': {e}")
                emit_searching(f"角度「{angle_name}」搜索失败", str(e))
                continue

        # Step 3: Merge and deduplicate across all angles
        emit_processing(
            "合并搜索结果...",
            f"合并前: {len(all_results)} 篇",
        )
        merged = self._deduplicate_by_article_id(all_results, max_results)
        emit_processing(
            f"去重后共 {len(merged)} 篇文章",
            None,
        )

        if not merged:
            emit_processing("未找到相关文章", None)
            return f"未能找到与「{topic}」相关的新闻文章，请尝试更换关键词。"

        # Step 4: Generate comprehensive report
        emit_summarizing("生成综合研究报告...", f"基于 {len(merged)} 篇文章")
        report = self._generate_report(topic, merged)

        # Step 5: Build final output
        output_parts = []
        output_parts.append(f"# 深度研究报告：{topic}")
        output_parts.append(f"*基于 {len(merged)} 篇相关文章的多角度分析*")
        output_parts.append("")
        output_parts.append(report)
        output_parts.append("")
        output_parts.append("---")
        output_parts.append("## 参考文章")
        for i, r in enumerate(merged, 1):
            published = r.published_at or "未知日期"
            category = r.category or "未分类"
            output_parts.append(
                f"{i}. 「{r.title}」 [{category}] ({published})\n   {r.url}"
            )

        emit_processing("深度研究完成", f"主题: {topic[:50]}, 文章数: {len(merged)}")
        return "\n".join(output_parts)

    def _generate_angles(self, topic: str, n: int = 4) -> list[dict]:
        """
        Generate search angles for a topic using LLM.

        Args:
            topic: The research topic
            n: Number of angles to generate

        Returns:
            List of dicts with 'angle' (Chinese name) and 'query' (English search query)
        """
        emit_analyzing("生成研究角度...", f"主题: {topic[:60]}")

        current_date = datetime.now().strftime("%B %d, %Y")
        prompt = ANGLE_GENERATION_PROMPT.format(
            n=n,
            current_date=current_date,
            topic=topic,
        )

        try:
            response = self.llm_service.generate(
                prompt, max_tokens=500, temperature=0.4
            )

            # Parse JSON response, handling markdown code blocks
            response = response.strip()
            if response.startswith("```"):
                response = response.split("\n", 1)[1]
                response = response.rsplit("```", 1)[0]

            data = json.loads(response)
            angles = data.get("angles", [])

            if not angles or not isinstance(angles, list):
                raise ValueError("Empty or invalid angles list")

            # Validate each angle has required fields
            valid_angles = []
            for angle in angles:
                if isinstance(angle, dict) and "angle" in angle and "query" in angle:
                    valid_angles.append(angle)

            if not valid_angles:
                raise ValueError("No valid angles found in response")

            logger.info(
                f"Generated {len(valid_angles)} search angles for topic: {topic[:50]}"
            )
            return valid_angles[:n]

        except Exception as e:
            logger.warning(f"Angle generation failed: {e}, using defaults")
            emit_analyzing("角度生成失败，使用默认角度", str(e))
            return self._fallback_angles(topic)

    def _fallback_angles(self, topic: str) -> list[dict]:
        """
        Generate fallback search angles when LLM fails.

        Uses predefined angle templates with the topic injected.

        Args:
            topic: The research topic

        Returns:
            List of fallback angle dicts
        """
        angles = []
        for template in _DEFAULT_ANGLES:
            query = f"{topic} {template['query']}".strip()
            angles.append({
                "angle": template["angle"],
                "query": query,
            })
        return angles

    @staticmethod
    def _deduplicate_by_article_id(results: list, limit: int) -> list:
        """
        Deduplicate search results by article_id across all angles.

        Keeps the result with the highest score for each unique article.

        Args:
            results: Combined results from all search angles
            limit: Maximum number of results to return

        Returns:
            Deduplicated and limited list of results
        """
        seen = {}
        for r in results:
            if r.article_id not in seen or r.score > seen[r.article_id].score:
                seen[r.article_id] = r
        # Sort by score descending
        sorted_results = sorted(seen.values(), key=lambda r: r.score, reverse=True)
        return sorted_results[:limit]

    def _generate_report(self, topic: str, results: list) -> str:
        """
        Generate a comprehensive research report using LLM.

        Args:
            topic: The research topic
            results: Deduplicated search results

        Returns:
            Chinese research report text
        """
        # Build article summaries for the prompt
        article_parts = []
        for i, r in enumerate(results, 1):
            parts = [f"[{i}] 标题: {r.title}"]
            if r.category:
                parts.append(f"    分类: {r.category}")
            if r.published_at:
                parts.append(f"    发布时间: {r.published_at}")
            summary = getattr(r, "article_summary", None) or getattr(
                r, "chunk_summary", None
            )
            if summary:
                parts.append(f"    摘要: {summary}")
            if r.content:
                content_preview = (
                    r.content[:600] if len(r.content) > 600 else r.content
                )
                parts.append(f"    内容: {content_preview}")
            article_parts.append("\n".join(parts))

        articles_text = "\n\n".join(article_parts)
        current_date = datetime.now().strftime("%Y年%m月%d日")

        prompt = RESEARCH_REPORT_PROMPT.format(
            topic=topic,
            current_date=current_date,
            articles=articles_text,
        )

        try:
            emit_summarizing("调用 LLM 生成研究报告...", None)
            report = self.llm_service.generate(
                prompt, max_tokens=2048, temperature=0.3
            )
            emit_summarizing("研究报告生成完成", None)
            return report.strip()
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            emit_summarizing("报告生成失败，使用简要总结", str(e))
            return self._fallback_report(topic, results)

    @staticmethod
    def _fallback_report(topic: str, results: list) -> str:
        """
        Generate a simple fallback report when LLM fails.

        Args:
            topic: The research topic
            results: Search results

        Returns:
            Simple formatted report
        """
        lines = [
            f"## 概述",
            f"以下是关于「{topic}」的相关新闻汇总（共 {len(results)} 篇）。",
            "",
            "## 相关文章摘要",
        ]
        for i, r in enumerate(results, 1):
            summary = getattr(r, "article_summary", None) or getattr(
                r, "chunk_summary", None
            )
            if summary:
                lines.append(f"{i}. 「{r.title}」：{summary}")
            else:
                lines.append(f"{i}. 「{r.title}」")
        lines.append("")
        lines.append("*注：由于分析服务暂时不可用，仅提供文章摘要。*")
        return "\n".join(lines)


# ===== Factory Function =====

_deep_research_tool: Optional[DeepResearchTool] = None


def get_deep_research_tool() -> DeepResearchTool:
    """Get singleton deep research tool instance."""
    global _deep_research_tool
    if _deep_research_tool is None:
        _deep_research_tool = DeepResearchTool()
    return _deep_research_tool


def create_deep_research_tool() -> FunctionTool:
    """
    Create a LlamaIndex FunctionTool for deep research.

    Returns:
        FunctionTool: Ready-to-use tool for LlamaIndex agent
    """
    tool = get_deep_research_tool()

    return FunctionTool.from_defaults(
        fn=tool.deep_research,
        name="deep_research",
        description="""
Conduct deep, multi-angle research on a topic using WSJ news articles.

Unlike the basic news_query tool which performs a single search, this tool:
- Generates multiple research angles/perspectives for the topic using AI
- Searches for articles from each angle independently
- Merges and deduplicates results across all perspectives
- Synthesizes a comprehensive Chinese research report with citations

Best for:
- Complex topics that benefit from multi-perspective analysis
- When the user asks for "deep research", "comprehensive analysis", or "in-depth report"
- Topics spanning multiple domains (e.g., economic policy affecting tech industry)
- When the user uses keywords like "深度研究", "全面分析", "深入分析", "研究报告"

Parameters:
- topic: The research topic (any language, e.g., "AI对就业市场的影响", "Federal Reserve interest rate policy")
- max_results: Maximum total articles to gather across all angles (3-20, default 10)

Examples:
- deep_research("美中贸易关系最新发展")
- deep_research("AI regulation and its impact on tech companies", max_results=15)
- deep_research("全球半导体供应链变化", max_results=8)

Use this tool when the user wants a thorough, multi-faceted analysis rather than a simple search.
""",
    )
