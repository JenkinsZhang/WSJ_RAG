"""
Date parser for WSJ article timestamps.

Handles various date formats found in WSJ articles:
    - "Updated Jan. 23, 2026 4:39 pm ET"
    - "Jan. 23, 2026"
    - "January 23, 2026 at 4:39 pm ET"
    - "2026-01-23T16:39:00Z" (ISO format)
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


class DateParser:
    """
    Parser for WSJ date formats.

    Converts various WSJ timestamp strings to datetime objects.
    Handles timezone abbreviations by stripping them (assumes ET/UTC).

    Example:
        >>> parser = DateParser()
        >>> dt = parser.parse("Updated Jan. 23, 2026 4:39 pm ET")
        >>> print(dt.isoformat())
        2026-01-23T16:39:00
    """

    # Month abbreviations mapping
    MONTH_MAP = {
        "jan": 1, "jan.": 1, "january": 1,
        "feb": 2, "feb.": 2, "february": 2,
        "mar": 3, "mar.": 3, "march": 3,
        "apr": 4, "apr.": 4, "april": 4,
        "may": 5,
        "jun": 6, "jun.": 6, "june": 6,
        "jul": 7, "jul.": 7, "july": 7,
        "aug": 8, "aug.": 8, "august": 8,
        "sep": 9, "sep.": 9, "sept": 9, "sept.": 9, "september": 9,
        "oct": 10, "oct.": 10, "october": 10,
        "nov": 11, "nov.": 11, "november": 11,
        "dec": 12, "dec.": 12, "december": 12,
    }

    # Patterns to try in order
    PATTERNS = [
        # ISO format: 2026-01-23T16:39:00Z
        r"(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})",
        # Updated Jan. 23, 2026 4:39 pm ET
        r"(?:Updated\s+)?(\w+\.?)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(am|pm)",
        # Jan. 23, 2026
        r"(\w+\.?)\s+(\d{1,2}),?\s+(\d{4})",
        # 23 Jan 2026
        r"(\d{1,2})\s+(\w+\.?)\s+(\d{4})",
    ]

    def parse(self, date_str: Optional[str]) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.

        Args:
            date_str: Date string from WSJ article

        Returns:
            datetime: Parsed datetime or None if parsing fails
        """
        if not date_str:
            return None

        date_str = date_str.strip()

        # Try ISO format first
        iso_result = self._try_iso_format(date_str)
        if iso_result:
            return iso_result

        # Try WSJ formats
        wsj_result = self._try_wsj_formats(date_str)
        if wsj_result:
            return wsj_result

        logger.warning(f"Could not parse date: {date_str}")
        return None

    def _try_iso_format(self, date_str: str) -> Optional[datetime]:
        """Try parsing ISO 8601 format."""
        try:
            # Handle various ISO formats
            cleaned = date_str.replace("Z", "+00:00")
            if "T" in cleaned:
                # Remove timezone for naive datetime
                cleaned = re.sub(r"[+-]\d{2}:\d{2}$", "", cleaned)
                return datetime.fromisoformat(cleaned)
        except ValueError:
            pass
        return None

    def _try_wsj_formats(self, date_str: str) -> Optional[datetime]:
        """Try parsing WSJ-specific formats."""
        # Clean up the string
        cleaned = date_str.lower()
        cleaned = re.sub(r"\s*(et|est|edt|pt|pst|pdt|utc|gmt)\s*$", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+at\s+", " ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Pattern 1: "updated jan. 23, 2026 4:39 pm" or "jan. 23, 2026 4:39 pm"
        match = re.search(
            r"(?:updated\s+)?(\w+\.?)\s+(\d{1,2}),?\s+(\d{4})\s+(\d{1,2}):(\d{2})\s*(am|pm)?",
            cleaned
        )
        if match:
            month_str, day, year, hour, minute, ampm = match.groups()
            month = self.MONTH_MAP.get(month_str.lower())
            if month:
                hour = int(hour)
                if ampm:
                    if ampm.lower() == "pm" and hour != 12:
                        hour += 12
                    elif ampm.lower() == "am" and hour == 12:
                        hour = 0
                try:
                    return datetime(int(year), month, int(day), hour, int(minute))
                except ValueError as e:
                    logger.debug(f"Invalid date values: {e}")

        # Pattern 2: "jan. 23, 2026" (date only)
        match = re.search(r"(\w+\.?)\s+(\d{1,2}),?\s+(\d{4})", cleaned)
        if match:
            month_str, day, year = match.groups()
            month = self.MONTH_MAP.get(month_str.lower())
            if month:
                try:
                    return datetime(int(year), month, int(day))
                except ValueError as e:
                    logger.debug(f"Invalid date values: {e}")

        # Pattern 3: "23 jan 2026"
        match = re.search(r"(\d{1,2})\s+(\w+\.?)\s+(\d{4})", cleaned)
        if match:
            day, month_str, year = match.groups()
            month = self.MONTH_MAP.get(month_str.lower())
            if month:
                try:
                    return datetime(int(year), month, int(day))
                except ValueError as e:
                    logger.debug(f"Invalid date values: {e}")

        return None

    def to_iso(self, date_str: Optional[str]) -> Optional[str]:
        """
        Parse date string and return ISO format string.

        Args:
            date_str: Date string to parse

        Returns:
            str: ISO formatted date string or None
        """
        dt = self.parse(date_str)
        return dt.isoformat() if dt else None


# Module-level singleton
_parser: Optional[DateParser] = None


def get_date_parser() -> DateParser:
    """Get singleton DateParser instance."""
    global _parser
    if _parser is None:
        _parser = DateParser()
    return _parser
