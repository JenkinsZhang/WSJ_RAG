"""
URL utilities for WSJ RAG system.

Provides URL normalization to ensure consistent handling
across crawling, indexing, and searching operations.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def normalize_url(url: str) -> str:
    """
    Normalize URL by removing query parameters and fragments.

    This ensures the same article always produces the same ID,
    regardless of tracking parameters like ?mod=nav_top.

    Args:
        url: Raw URL string

    Returns:
        str: Normalized URL with only scheme, netloc, and path

    Examples:
        >>> normalize_url("https://wsj.com/tech/article?mod=nav")
        'https://wsj.com/tech/article'

        >>> normalize_url("https://wsj.com/tech/article#section")
        'https://wsj.com/tech/article'

        >>> normalize_url("https://wsj.com/tech/article/")
        'https://wsj.com/tech/article'
    """
    if not url:
        return url

    parsed = urlparse(url)

    # Rebuild URL with only scheme, netloc, and path
    normalized = urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path.rstrip('/'),  # Remove trailing slash
        '',  # params
        '',  # query
        '',  # fragment
    ))

    return normalized
