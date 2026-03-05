"""
Database information tool for the news agent.

Provides metadata queries: article counts, date ranges, category distribution,
and latest articles — without requiring vector search.
"""

from __future__ import annotations

import logging
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.progress import emit_processing, emit_searching

logger = logging.getLogger(__name__)


class DatabaseInfoTool:
    """Provides database metadata and statistics queries."""

    def __init__(self, repository: Optional[NewsRepository] = None):
        self._repository = repository

    @property
    def repository(self) -> NewsRepository:
        if self._repository is None:
            self._repository = NewsRepository(get_opensearch_client())
        return self._repository

    def database_info(
        self,
        query_type: str = "stats",
        category: Optional[str] = None,
        limit: int = 5,
    ) -> str:
        """
        Query database metadata: statistics, latest articles, or category info.

        Use this tool to answer questions about the database itself, such as:
        - How many articles are in the database
        - When was the latest/oldest article published
        - What categories are available and their article counts
        - What are the N most recent articles (by publish date)

        Args:
            query_type: Type of query. One of:
                - "stats": Overall statistics (article count, date range, categories)
                - "latest": Get the most recently published articles
                - "categories": Category distribution details
            category: Optional category filter (for "latest" query_type)
            limit: Number of articles for "latest" query (1-20, default 5)

        Returns:
            Formatted string with the requested database information.
        """
        limit = max(1, min(20, limit))

        if query_type == "latest":
            return self._get_latest(category, limit)
        elif query_type == "categories":
            return self._get_categories()
        else:
            return self._get_stats()

    def _get_stats(self) -> str:
        """Get overall database statistics."""
        emit_processing("查询数据库统计信息...", None)

        stats = self.repository.get_database_stats()

        if "error" in stats:
            return f"查询统计失败: {stats['error']}"

        lines = [
            "=== 数据库统计 ===",
            f"总文章数: {stats.get('total_articles', 'N/A')}",
            f"总分块数: {stats.get('total_chunks', 'N/A')}",
            f"最新文章日期: {stats.get('latest_date', 'N/A')}",
            f"最早文章日期: {stats.get('oldest_date', 'N/A')}",
        ]

        categories = stats.get("categories", {})
        if categories:
            lines.append("")
            lines.append("分类分布:")
            for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
                lines.append(f"  {cat}: {count} 条记录")

        emit_processing("统计查询完成", f"{stats.get('total_articles', 0)} 篇文章")
        return "\n".join(lines)

    def _get_latest(self, category: Optional[str], limit: int) -> str:
        """Get the most recently published articles."""
        emit_searching(
            f"查询最近 {limit} 篇文章...",
            f"分类: {category or '全部'}"
        )

        results = self.repository.get_latest_articles(limit=limit, category=category)

        if not results:
            return "数据库中没有找到文章。"

        lines = [f"=== 最新 {len(results)} 篇文章 ===", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. 「{r.title}」")
            lines.append(f"   分类: {r.category or 'N/A'} | 发布: {r.published_at or 'N/A'}")
            lines.append(f"   URL: {r.url}")
            if r.article_summary:
                lines.append(f"   摘要: {r.article_summary[:150]}...")
            lines.append("")

        emit_processing("查询完成", f"返回 {len(results)} 篇文章")
        return "\n".join(lines)

    def _get_categories(self) -> str:
        """Get category distribution."""
        emit_processing("查询分类分布...", None)

        stats = self.repository.get_database_stats()
        categories = stats.get("categories", {})

        if not categories:
            return "没有找到分类信息。"

        total_articles = stats.get("total_articles", 0)
        lines = [
            f"=== 分类分布 (共 {total_articles} 篇文章) ===",
            "",
        ]
        for cat, count in sorted(categories.items(), key=lambda x: -x[1]):
            lines.append(f"  {cat}: {count} 条记录")

        emit_processing("分类查询完成", None)
        return "\n".join(lines)


def create_database_info_tool() -> FunctionTool:
    """Create a LlamaIndex FunctionTool for database info queries."""
    tool = DatabaseInfoTool()
    return FunctionTool.from_defaults(
        fn=tool.database_info,
        name="database_info",
        description="""Query database metadata and statistics.

Use this tool when the user asks about:
- Database status: "数据库里有多少文章", "有多少数据"
- Date ranges: "最新的文章是什么时候的", "数据库最早的文章", "数据更新到几号了"
- Latest articles: "最新的几篇文章是什么", "最近入库的文章"
- Categories: "有哪些分类", "各分类有多少文章"

Do NOT use this tool for searching news by topic — use news_query instead.

Parameters:
- query_type: "stats" (overview), "latest" (recent articles), "categories" (distribution)
- category: Optional filter for "latest" query
- limit: Number of articles for "latest" (1-20, default 5)
""",
    )
