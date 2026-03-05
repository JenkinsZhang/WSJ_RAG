"""
Multi-topic news comparison tool for LlamaIndex agent.

Provides the ability to compare news coverage across multiple topics,
identifying commonalities, differences, and emerging trends. Uses
hybrid search to find relevant articles per topic, then leverages
LLM to produce a structured comparison report in Chinese.
"""

from __future__ import annotations

import logging
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.embedding import EmbeddingService, get_embedding_service
from src.clients.llm import LLMService, get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.models import deduplicate_results
from src.agent.progress import emit_processing, emit_searching, emit_summarizing

logger = logging.getLogger(__name__)


COMPARISON_PROMPT = """你是一位资深新闻分析师。请根据以下多个主题的新闻文章，撰写一份结构化的对比分析报告。

主题列表：{topics}

各主题的新闻内容：
{content}

请按照以下结构输出分析报告（用中文）：

## 各主题概述
对每个主题的最新动态进行简要概述（每个主题2-3句话）。

## 共同点
分析这些主题之间的共同趋势、关联事件或共享的影响因素。

## 关键差异
指出各主题之间的核心差异，包括发展方向、市场表现、政策影响等方面。

## 趋势分析
基于以上新闻内容，分析未来可能的发展趋势和值得关注的动向。

请确保分析客观、有深度，并引用具体的新闻内容作为论据。"""


class CompareArticlesTool:
    """
    Multi-topic news comparison tool.

    Searches for articles on each provided topic, then uses LLM
    to generate a structured comparison covering overviews,
    commonalities, key differences, and trend analysis.

    Example:
        >>> tool = CompareArticlesTool()
        >>> report = tool.compare_articles("Tesla,BYD")
    """

    def __init__(
        self,
        embedding_service: Optional[EmbeddingService] = None,
        repository: Optional[NewsRepository] = None,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        """Initialize the comparison tool with optional service overrides."""
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

    def compare_articles(self, topics: str, max_per_topic: int = 3) -> str:
        """
        Compare news articles across multiple topics.

        Searches for relevant articles on each topic, deduplicates results,
        and generates a structured comparison report using LLM.

        Args:
            topics: Comma-separated list of topics to compare, e.g. "Tesla,BYD".
                    Supports 2-4 topics.
            max_per_topic: Maximum number of articles to retrieve per topic (1-5, default 3).

        Returns:
            A formatted comparison report containing LLM analysis and
            raw article data per topic.
        """
        # Parse and validate topics
        topic_list = [t.strip() for t in topics.split(",") if t.strip()]

        if len(topic_list) < 2:
            return "Error: Please provide at least 2 topics separated by commas (e.g. 'Tesla,BYD')."
        if len(topic_list) > 4:
            return "Error: Maximum 4 topics allowed. Please reduce the number of topics."

        max_per_topic = max(1, min(5, max_per_topic))

        emit_processing(
            "开始多主题对比分析...",
            f"主题: {', '.join(topic_list)}, 每个主题最多 {max_per_topic} 篇",
        )

        # Search for articles per topic
        topic_articles: dict[str, list[dict]] = {}

        for i, topic in enumerate(topic_list, 1):
            emit_searching(
                f"搜索主题 [{i}/{len(topic_list)}]: {topic}",
                f"最多 {max_per_topic} 篇文章",
            )

            try:
                query_vector = self.embedding_service.embed_text(topic)
                results = self.repository.hybrid_search(
                    query_text=topic,
                    query_vector=query_vector,
                    k=max_per_topic * 2,
                    vector_boost=0.6,
                    text_boost=0.4,
                )

                deduped = deduplicate_results(results, max_per_topic)

                articles = []
                for r in deduped:
                    articles.append({
                        "title": r.title or "N/A",
                        "summary": r.article_summary or r.chunk_summary or "",
                        "content": r.content or "",
                        "url": r.url or "",
                        "published_at": r.published_at or "",
                        "category": r.category or "",
                    })

                topic_articles[topic] = articles
                emit_searching(
                    f"主题 '{topic}' 找到 {len(articles)} 篇文章",
                    ", ".join(a["title"][:30] for a in articles[:3]) if articles else None,
                )

            except Exception as e:
                logger.warning(f"Failed to search topic '{topic}': {e}")
                topic_articles[topic] = []
                emit_searching(f"主题 '{topic}' 搜索失败", str(e))

        # Check if we have enough content
        total_articles = sum(len(arts) for arts in topic_articles.values())
        if total_articles == 0:
            emit_processing("未找到任何相关文章", None)
            return f"No articles found for any of the topics: {', '.join(topic_list)}"

        # Build content for LLM prompt
        content_parts = []
        for topic, articles in topic_articles.items():
            content_parts.append(f"### {topic}")
            if not articles:
                content_parts.append("(No articles found for this topic)")
                content_parts.append("")
                continue
            for j, art in enumerate(articles, 1):
                content_parts.append(f"[{j}] {art['title']}")
                if art["summary"]:
                    content_parts.append(f"    Summary: {art['summary']}")
                if art["content"]:
                    preview = art["content"][:400] + "..." if len(art["content"]) > 400 else art["content"]
                    content_parts.append(f"    Content: {preview}")
                content_parts.append("")

        combined_content = "\n".join(content_parts)

        # Generate comparison via LLM
        emit_summarizing("调用 LLM 生成对比分析报告...", f"共 {total_articles} 篇文章")

        comparison_text = ""
        try:
            prompt = COMPARISON_PROMPT.format(
                topics=", ".join(topic_list),
                content=combined_content,
            )
            comparison_text = self.llm_service.generate(
                prompt, max_tokens=2048, temperature=0.4
            )
            emit_summarizing("对比分析报告生成完成", None)
        except Exception as e:
            logger.warning(f"LLM comparison failed: {e}")
            emit_summarizing("LLM 分析失败，使用原始数据", str(e))
            # Fallback: build a simple comparison from raw data
            fallback_parts = ["## 对比分析（LLM 生成失败，以下为原始数据摘要）\n"]
            for topic, articles in topic_articles.items():
                fallback_parts.append(f"### {topic}")
                if not articles:
                    fallback_parts.append("- No articles found")
                else:
                    for art in articles:
                        fallback_parts.append(f"- {art['title']}")
                        if art["summary"]:
                            fallback_parts.append(f"  {art['summary']}")
                fallback_parts.append("")
            comparison_text = "\n".join(fallback_parts)

        # Build final report: LLM analysis + raw data appendix
        report_parts = [
            "=== 多主题对比分析报告 ===",
            f"主题: {', '.join(topic_list)}",
            "",
            comparison_text,
            "",
            "=== 原始文章数据 ===",
        ]

        for topic, articles in topic_articles.items():
            report_parts.append(f"\n--- {topic} ({len(articles)} articles) ---")
            if not articles:
                report_parts.append("No articles found.")
                continue
            for j, art in enumerate(articles, 1):
                report_parts.append(f"[{j}] {art['title']}")
                report_parts.append(f"    Published: {art['published_at'] or 'N/A'}")
                report_parts.append(f"    Category: {art['category'] or 'N/A'}")
                report_parts.append(f"    URL: {art['url'] or 'N/A'}")
                if art["summary"]:
                    report_parts.append(f"    Summary: {art['summary']}")
                report_parts.append("")

        emit_processing(
            "对比分析完成",
            f"{len(topic_list)} 个主题, 共 {total_articles} 篇文章",
        )

        return "\n".join(report_parts)


def create_compare_articles_tool() -> FunctionTool:
    """
    Create a LlamaIndex FunctionTool for multi-topic news comparison.

    Returns:
        FunctionTool: Ready-to-use comparison tool for LlamaIndex agent
    """
    tool = CompareArticlesTool()

    return FunctionTool.from_defaults(
        fn=tool.compare_articles,
        name="compare_articles",
        description="""
Compare news coverage across multiple topics and generate a structured analysis report.

This tool searches for relevant WSJ articles on each topic, then produces a
comparison report covering:
- Overview of each topic's latest developments
- Commonalities and shared trends between topics
- Key differences in direction, market performance, or policy impact
- Forward-looking trend analysis

Parameters:
- topics: Comma-separated list of 2-4 topics to compare (e.g. "Tesla,BYD" or "AI,Quantum Computing,Robotics")
- max_per_topic: Maximum articles to retrieve per topic (1-5, default 3)

Examples:
- compare_articles("Tesla,BYD")
- compare_articles("Apple,Google,Microsoft", max_per_topic=4)
- compare_articles("Fed policy,inflation,employment")

Use this tool when the user wants to compare, contrast, or analyze relationships
between multiple news topics, companies, or events.
""",
    )
