"""
Shared data models and utilities for agent tools.

Contains common data classes (QueryIntent, NewsQueryResult, SearchEvaluation)
and shared utility functions (deduplication, result conversion) used across
multiple agent tools.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class SearchMode(str, Enum):
    """Search mode for news query."""

    SEMANTIC = "semantic"
    HYBRID = "hybrid"
    RECENT = "recent"


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
        return cls(
            search_query=data.get("search_query", ""),
            mode=data.get("mode", "hybrid"),
            exclusive_only=data.get("exclusive_only", False),
            needs_summary=data.get("needs_summary", False),
            category=data.get("category"),
            hours_ago=data.get("hours_ago"),
        )


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


def deduplicate_results(results: list, limit: int) -> list:
    """Deduplicate search results by article_id, keeping highest score."""
    seen = {}
    for r in results:
        if r.article_id not in seen or r.score > seen[r.article_id].score:
            seen[r.article_id] = r
    return list(seen.values())[:limit]


def to_query_results(results: list) -> list[NewsQueryResult]:
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
