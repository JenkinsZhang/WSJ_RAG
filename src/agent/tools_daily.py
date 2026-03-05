"""
Daily news briefing tool for LlamaIndex agent.

Generates a comprehensive daily news summary by:
    1. Fetching all articles for a given date (OpenSearch date range query)
    2. Grouping by category and deduplicating
    3. Generating per-category summaries in parallel (first LLM pass)
    4. Synthesizing a full daily briefing report (second LLM pass)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, date, timedelta
from typing import Optional

from llama_index.core.tools import FunctionTool

from src.clients.llm import LLMService, get_llm_service
from src.clients.opensearch import get_opensearch_client
from src.storage.repository import NewsRepository
from src.agent.progress import emit_processing, emit_searching, emit_summarizing

logger = logging.getLogger(__name__)

_CATEGORY_NAMES = {
    "home": "综合", "world": "国际", "china": "中国",
    "tech": "科技", "finance": "金融", "business": "商业",
    "politics": "政治", "economy": "经济", "opinion": "观点",
    "arts": "文化", "lifestyle": "生活", "health": "健康",
    "sports": "体育", "us-news": "美国", "real-estate": "房产",
    "personal-finance": "个人理财", "style": "时尚",
}

CATEGORY_SUMMARY_PROMPT = """你是一位资深新闻编辑。请根据以下「{category}」领域的新闻文章，撰写该领域的每日摘要。

文章列表：
{articles}

要求：
- 用中文撰写，300-500字
- 概括该领域当天的主要事件和动态
- 指出最重要的1-2条新闻并展开分析
- 提及关键人物、公司或组织
- 语言专业流畅，像正式新闻简报
- 引用文章时使用「标题」格式

直接输出摘要内容，不要加标题或前缀。"""

DAILY_REPORT_PROMPT = """你是华尔街日报的资深主编。请根据以下各领域的新闻摘要，撰写一份完整的每日新闻总结报告。

日期：{date}

各领域摘要：
{summaries}

请按照以下结构撰写报告（用中文）：

# 每日新闻总结 — {date_display}

## 今日概览
用3-5句话总览当天新闻格局，点明最重要的主题和事件走向。

## 头条要闻
挑选当天最重要的3-5条新闻，每条用一个小标题+2-3段详细分析。要有深度，结合背景和影响。每条头条200-300字。

## 各领域详报
对每个有内容的领域撰写详细报道段落。每个领域150-300字，不要只是罗列，要有分析和关联。

## 市场与政策影响
跨领域分析：这些新闻对市场、政策、行业的综合影响。指出不同领域之间的关联。200-300字。

## 值得关注
列出2-3个值得后续跟踪的发展方向或待观察的事件。

要求：
- 总字数 2000-3000 字
- 语言专业、客观、有深度
- 像一份正式的每日新闻简报
- 引用具体新闻时使用「标题」格式
- 不要显示文章数量、篇数等统计信息
- 直接输出完整报告"""


class DailyBriefingTool:
    """
    Daily news briefing generator.

    Two-pass LLM architecture:
        Pass 1: Per-category summaries (parallel via ThreadPoolExecutor)
        Pass 2: Synthesize all category summaries into final report
    """

    def __init__(
        self,
        repository: Optional[NewsRepository] = None,
        llm_service: Optional[LLMService] = None,
    ) -> None:
        self._repository = repository
        self._llm_service = llm_service

    @property
    def repository(self) -> NewsRepository:
        if self._repository is None:
            self._repository = NewsRepository(get_opensearch_client())
        return self._repository

    @property
    def llm_service(self) -> LLMService:
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    def daily_briefing(self, target_date: Optional[str] = None) -> str:
        """
        Generate a comprehensive daily news briefing report.

        Fetches all articles for the specified date, groups them by category,
        generates per-category summaries in parallel, then synthesizes a full
        daily report.

        Args:
            target_date: Date in YYYY-MM-DD format. Defaults to today.
                         Use "yesterday" for yesterday's briefing.

        Returns:
            A comprehensive daily news briefing in Chinese (2000-3000 words),
            covering headlines, per-category analysis, cross-domain impact,
            and forward-looking insights.

        Examples:
            - daily_briefing() → today's briefing
            - daily_briefing("2026-03-04") → specific date
            - daily_briefing("yesterday") → yesterday's briefing
        """
        today = date.today()
        if not target_date or target_date.lower() in ("today", "今天"):
            report_date = today
        elif target_date.lower() in ("yesterday", "昨天"):
            report_date = today - timedelta(days=1)
        else:
            try:
                report_date = date.fromisoformat(target_date)
            except ValueError:
                return f"日期格式错误: {target_date}，请使用 YYYY-MM-DD 格式。"

        date_display = f"{report_date.year}年{report_date.month}月{report_date.day}日"
        weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
        date_display += f"（{weekdays[report_date.weekday()]}）"

        emit_processing("开始生成每日新闻总结...", date_display)

        # Fetch articles by exact date range
        articles = self._fetch_articles_for_date(report_date)
        if not articles:
            return f"未找到 {date_display} 的新闻文章。"

        # Group by category
        grouped = self._group_by_category(articles)
        emit_processing(
            "文章分组完成",
            f"涵盖 {len(grouped)} 个领域",
        )

        # Pass 1: per-category summaries (parallel)
        category_summaries = self._generate_category_summaries_parallel(grouped)
        if not category_summaries:
            return f"{date_display} 的文章内容不足以生成总结。"

        # Pass 2: synthesize final report
        report = self._synthesize_report(
            report_date.isoformat(), date_display, category_summaries
        )

        emit_processing("每日新闻总结生成完成", None)
        return report

    def _fetch_articles_for_date(self, report_date: date) -> list:
        """Fetch all articles for a specific date using OpenSearch date range query."""
        emit_searching("获取当天新闻文章...", report_date.isoformat())

        results = self.repository.get_articles_by_date(
            target_date=report_date.isoformat(), limit=500
        )

        emit_searching("文章获取完成", None)
        return results

    def _group_by_category(self, articles: list) -> dict[str, list]:
        """Group articles by category, deduplicate by article_id."""
        grouped = defaultdict(list)
        seen_ids = set()

        for r in articles:
            if r.article_id in seen_ids:
                continue
            seen_ids.add(r.article_id)
            category = r.category or "uncategorized"
            grouped[category].append(r)

        return dict(grouped)

    def _summarize_category(self, category: str, articles: list) -> tuple[str, str]:
        """Generate summary for a single category. Returns (category, summary)."""
        display_name = _CATEGORY_NAMES.get(category, category)

        article_parts = []
        for r in articles:
            parts = [f"- 「{r.title}」"]
            summary = r.article_summary or r.chunk_summary
            if summary:
                parts.append(f"  摘要: {summary}")
            elif r.content:
                parts.append(f"  内容: {r.content[:300]}")
            article_parts.append("\n".join(parts))

        articles_text = "\n\n".join(article_parts)

        try:
            prompt = CATEGORY_SUMMARY_PROMPT.format(
                category=display_name,
                articles=articles_text,
            )
            summary = self.llm_service.generate(
                prompt, max_tokens=1024, temperature=0.3
            )
            return category, summary.strip()
        except Exception as e:
            logger.warning(f"Category summary failed for {category}: {e}")
            titles = "\n".join(f"- 「{r.title}」" for r in articles)
            return category, f"（摘要生成失败）\n相关报道：\n{titles}"

    def _generate_category_summaries_parallel(
        self, grouped: dict[str, list]
    ) -> dict[str, str]:
        """Generate LLM summaries for all categories in parallel (Pass 1)."""
        summaries = {}
        total = len(grouped)

        emit_summarizing(f"并行生成 {total} 个分类摘要...", None)

        with ThreadPoolExecutor(max_workers=min(total, 5)) as executor:
            futures = {
                executor.submit(self._summarize_category, cat, arts): cat
                for cat, arts in grouped.items()
            }

            for future in as_completed(futures):
                cat = futures[future]
                display_name = _CATEGORY_NAMES.get(cat, cat)
                try:
                    _, summary = future.result()
                    summaries[cat] = summary
                    emit_summarizing(f"分类摘要完成: {display_name}", None)
                except Exception as e:
                    logger.warning(f"Category summary failed for {cat}: {e}")
                    summaries[cat] = f"（摘要生成失败: {e}）"

        return summaries

    def _synthesize_report(
        self, date_iso: str, date_display: str, category_summaries: dict[str, str]
    ) -> str:
        """Synthesize final daily report from category summaries (Pass 2)."""
        emit_summarizing("综合各领域摘要，生成完整报告...", None)

        summary_parts = []
        for category, summary in category_summaries.items():
            display_name = _CATEGORY_NAMES.get(category, category)
            summary_parts.append(f"### {display_name}\n{summary}")

        summaries_text = "\n\n".join(summary_parts)

        prompt = DAILY_REPORT_PROMPT.format(
            date=date_iso,
            date_display=date_display,
            summaries=summaries_text,
        )

        try:
            report = self.llm_service.generate(
                prompt, max_tokens=8192, temperature=0.4
            )
            emit_summarizing("报告生成完成", None)
            return report.strip()
        except Exception as e:
            logger.error(f"Report synthesis failed: {e}")
            emit_summarizing("报告合成失败，使用分类摘要", str(e))
            fallback_parts = [f"# 每日新闻总结 — {date_display}\n"]
            for category, summary in category_summaries.items():
                display_name = _CATEGORY_NAMES.get(category, category)
                fallback_parts.append(f"## {display_name}\n{summary}\n")
            return "\n".join(fallback_parts)


def create_daily_briefing_tool() -> FunctionTool:
    """Create a LlamaIndex FunctionTool for daily news briefing."""
    tool = DailyBriefingTool()
    return FunctionTool.from_defaults(
        fn=tool.daily_briefing,
        name="daily_briefing",
        description="""Generate a comprehensive daily news briefing report.

This tool creates a detailed, professional daily news summary covering all categories,
with in-depth analysis, cross-domain insights, and forward-looking commentary.

Use this tool when the user asks for:
- Daily news summary: "今日新闻总结", "每日简报", "daily briefing"
- What happened today/yesterday: "今天发生了什么", "昨天的新闻"
- Comprehensive overview: "给我一份完整的新闻报告"

Parameters:
- target_date: Date in YYYY-MM-DD format, or "today"/"yesterday". Defaults to today.

Examples:
- daily_briefing() → today's briefing
- daily_briefing("yesterday") → yesterday's briefing
- daily_briefing("2026-03-04") → specific date

Do NOT use this for searching specific topics — use news_query instead.
Do NOT use this for trend analysis — use trend_analysis instead.
""",
    )
