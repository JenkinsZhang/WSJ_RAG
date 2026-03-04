"""
News trend analysis tool for LlamaIndex agent.

Provides trend analysis capabilities by aggregating recent news articles,
identifying category distributions, and using LLM to extract trending
topics and overall market/news trends.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.llm import LLMService, get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.progress import emit_processing, emit_searching, emit_summarizing

logger = logging.getLogger(__name__)


TREND_ANALYSIS_PROMPT = """You are a news trend analyst. Given the following list of recent news article titles, identify the top {top_n} trending topics.

Article titles:
{titles}

Total articles: {total}
Time range: last {hours} hours

Analyze these titles and output a JSON object with:
- "topics": a list of the top {top_n} trending topics, each with:
  - "topic": short topic name (in Chinese, 2-6 words)
  - "count": approximate number of articles related to this topic
  - "summary": one-sentence summary of this trend (in Chinese)
- "overall_trend": a 2-3 sentence overview of the current news landscape (in Chinese)

Output ONLY valid JSON, no other text.

Example output:
{{"topics": [{{"topic": "AI芯片竞争", "count": 5, "summary": "英伟达与AMD在AI芯片市场展开激烈竞争，推动算力成本持续下降。"}}], "overall_trend": "当前新闻焦点集中在科技行业和地缘政治领域。"}}
"""


class TrendAnalysisTool:
    """
    News trend analysis tool that aggregates recent articles
    and identifies trending topics using LLM analysis.

    Features:
        - Category distribution analysis
        - LLM-powered topic extraction
        - Configurable time range and topic count
        - Graceful fallback when LLM is unavailable

    Example:
        >>> tool = TrendAnalysisTool()
        >>> report = tool.trend_analysis(category="tech", hours=48, top_n=5)
    """

    def __init__(
        self,
        repository: Optional[NewsRepository] = None,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        """Initialize the trend analysis tool."""
        self._repository = repository
        self._llm_service = llm_service

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

    def trend_analysis(
        self,
        category: Optional[str] = None,
        hours: int = 72,
        top_n: int = 5,
    ) -> str:
        """
        Analyze recent news trends and identify hot topics.

        Args:
            category: Optional category filter (e.g., "tech", "finance").
                      If None, analyzes all categories.
            hours: How many hours to look back (1-720, default 72).
            top_n: Number of top trending topics to identify (1-10, default 5).

        Returns:
            A formatted trend analysis report including category distribution,
            top trending topics, and an overall trend summary.
        """
        # Validate inputs
        hours = max(1, min(720, hours))
        top_n = max(1, min(10, top_n))

        emit_processing(
            "开始趋势分析...",
            f"时间范围: {hours}小时, 类别: {category or '全部'}, Top {top_n}",
        )

        # Fetch recent articles
        emit_searching(
            f"获取最近 {hours} 小时的新闻...",
            f"类别: {category or '全部'}",
        )

        try:
            results = self.repository.get_recent_news(
                hours=hours, limit=200, category=category,
            )
        except Exception as e:
            logger.error(f"Failed to fetch recent news: {e}")
            emit_processing("获取新闻失败", str(e))
            return f"Error fetching recent news: {e}"

        if not results:
            emit_processing("未找到新闻文章", None)
            return (
                f"No news articles found in the last {hours} hours"
                + (f" for category '{category}'" if category else "")
                + "."
            )

        emit_searching(f"找到 {len(results)} 篇文章", None)

        # Deduplicate by article_id
        seen_ids = set()
        unique_results = []
        for r in results:
            if r.article_id not in seen_ids:
                seen_ids.add(r.article_id)
                unique_results.append(r)

        # Category distribution
        category_counter = Counter(
            r.category for r in unique_results if r.category
        )

        emit_processing(
            "统计分类分布...",
            f"共 {len(unique_results)} 篇独立文章, {len(category_counter)} 个分类",
        )

        # Build category distribution text
        category_lines = []
        for cat, count in category_counter.most_common():
            category_lines.append(f"  - {cat}: {count} 篇")
        category_report = "\n".join(category_lines) if category_lines else "  (无分类信息)"

        # Collect titles for LLM analysis
        titles = [r.title for r in unique_results if r.title]

        # LLM trend analysis
        topic_report = ""
        overall_trend = ""

        if titles:
            emit_summarizing(
                "调用 LLM 分析趋势...",
                f"共 {len(titles)} 个标题",
            )

            titles_text = "\n".join(f"- {t}" for t in titles[:100])
            prompt = TREND_ANALYSIS_PROMPT.format(
                top_n=top_n,
                titles=titles_text,
                total=len(titles),
                hours=hours,
            )

            try:
                response = self.llm_service.generate(
                    prompt, max_tokens=800, temperature=0.3,
                )

                # Parse JSON response
                response = response.strip()
                if response.startswith("```"):
                    response = response.split("\n", 1)[1]
                    response = response.rsplit("```", 1)[0]

                data = json.loads(response)
                topics = data.get("topics", [])
                overall_trend = data.get("overall_trend", "")

                emit_summarizing(
                    "趋势分析完成",
                    f"识别出 {len(topics)} 个热门话题",
                )

                # Build topic report
                topic_lines = []
                for i, topic in enumerate(topics[:top_n], 1):
                    name = topic.get("topic", "未知")
                    count = topic.get("count", "?")
                    summary = topic.get("summary", "")
                    topic_lines.append(f"  {i}. {name} (约 {count} 篇)")
                    if summary:
                        topic_lines.append(f"     {summary}")
                topic_report = "\n".join(topic_lines)

            except json.JSONDecodeError as e:
                logger.warning(f"Failed to parse trend analysis JSON: {e}")
                emit_summarizing("LLM 返回格式异常，使用基础统计", str(e))
                topic_report = self._fallback_topic_report(titles, top_n)
                overall_trend = ""
            except Exception as e:
                logger.warning(f"LLM trend analysis failed: {e}")
                emit_summarizing("LLM 分析失败，使用基础统计", str(e))
                topic_report = self._fallback_topic_report(titles, top_n)
                overall_trend = ""

        # Assemble final report
        report_parts = [
            f"=== 新闻趋势分析报告 ===",
            f"时间范围: 最近 {hours} 小时",
            f"文章总数: {len(unique_results)} 篇",
            "",
            "--- 分类分布 ---",
            category_report,
            "",
        ]

        if topic_report:
            report_parts.extend([
                f"--- 热门话题 Top {top_n} ---",
                topic_report,
                "",
            ])

        if overall_trend:
            report_parts.extend([
                "--- 整体趋势 ---",
                overall_trend,
                "",
            ])

        emit_processing("趋势分析报告生成完成", f"{len(unique_results)} 篇文章")

        return "\n".join(report_parts)

    @staticmethod
    def _fallback_topic_report(titles: list[str], top_n: int) -> str:
        """Generate a basic topic report from titles when LLM is unavailable."""
        lines = [f"  (基于标题的前 {min(top_n, len(titles))} 条新闻)"]
        for i, title in enumerate(titles[:top_n], 1):
            lines.append(f"  {i}. {title}")
        return "\n".join(lines)


# Singleton instance
_trend_analysis_tool: Optional[TrendAnalysisTool] = None


def get_trend_analysis_tool() -> TrendAnalysisTool:
    """Get singleton trend analysis tool instance."""
    global _trend_analysis_tool
    if _trend_analysis_tool is None:
        _trend_analysis_tool = TrendAnalysisTool()
    return _trend_analysis_tool


def create_trend_analysis_tool() -> FunctionTool:
    """
    Create a LlamaIndex FunctionTool for news trend analysis.

    Returns:
        FunctionTool: Ready-to-use tool for LlamaIndex agent
    """
    tool = get_trend_analysis_tool()

    return FunctionTool.from_defaults(
        fn=tool.trend_analysis,
        name="trend_analysis",
        description="""
Analyze recent news trends and identify hot topics from WSJ articles.

This tool aggregates recent news articles and provides:
- Category distribution (how many articles per category)
- Top trending topics identified by LLM analysis
- Overall trend summary of the current news landscape

Use this tool when the user asks about:
- News trends or hot topics ("最近有什么热点", "trending topics")
- Category-specific trends ("科技领域最近趋势", "finance trends")
- News landscape overview ("新闻概况", "what's trending")

Parameters:
- category: Optional category filter (tech, finance, business, politics, etc.)
- hours: Time range to analyze in hours (1-720, default 72 = 3 days)
- top_n: Number of top trending topics to identify (1-10, default 5)

Examples:
- trend_analysis() → overall trends from last 3 days
- trend_analysis(category="tech", hours=48) → tech trends from last 2 days
- trend_analysis(hours=168, top_n=10) → top 10 topics from last week
""",
    )
