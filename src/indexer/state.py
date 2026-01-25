"""
Index state management for tracking processed files.

Maintains a JSON file to track which articles have been indexed,
enabling incremental indexing and failure recovery.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class IndexState:
    """
    Manages the indexed files state.

    Tracks successfully indexed files and failed attempts to enable:
        - Incremental indexing (skip already processed files)
        - Failure recovery (retry failed files)
        - Progress reporting

    State file format:
        {
            "version": 1,
            "indexed": {
                "path/to/file.json": {
                    "article_id": "abc123",
                    "chunks": 3,
                    "indexed_at": "2026-01-25T15:30:00"
                }
            },
            "failed": {
                "path/to/bad.json": {
                    "error": "Empty content",
                    "failed_at": "2026-01-25T15:31:00"
                }
            }
        }

    Example:
        >>> state = IndexState("data/indexed_files.json")
        >>> if not state.is_indexed("articles/tech/article.json"):
        ...     # process article
        ...     state.mark_indexed("articles/tech/article.json", "abc123", 3)
        >>> state.save()
    """

    VERSION = 1

    def __init__(self, state_file: str | Path) -> None:
        """
        Initialize index state.

        Args:
            state_file: Path to the state JSON file
        """
        self.state_file = Path(state_file)
        self._indexed: dict[str, dict] = {}
        self._failed: dict[str, dict] = {}
        self._dirty = False
        self._load()

    def _load(self) -> None:
        """Load state from file if it exists."""
        if not self.state_file.exists():
            logger.info(f"State file not found, starting fresh: {self.state_file}")
            return

        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            version = data.get("version", 1)
            if version != self.VERSION:
                logger.warning(f"State file version mismatch: {version} != {self.VERSION}")

            self._indexed = data.get("indexed", {})
            self._failed = data.get("failed", {})
            logger.info(f"Loaded state: {len(self._indexed)} indexed, {len(self._failed)} failed")

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load state file: {e}")
            self._indexed = {}
            self._failed = {}

    def save(self) -> None:
        """Save current state to file."""
        if not self._dirty:
            return

        # Ensure directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "version": self.VERSION,
            "indexed": self._indexed,
            "failed": self._failed,
        }

        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            self._dirty = False
            logger.debug(f"Saved state to {self.state_file}")
        except IOError as e:
            logger.error(f"Failed to save state file: {e}")

    def _normalize_path(self, file_path: str | Path) -> str:
        """Normalize file path for consistent keys."""
        return str(Path(file_path)).replace("\\", "/")

    def is_indexed(self, file_path: str | Path) -> bool:
        """
        Check if a file has been successfully indexed.

        Args:
            file_path: Path to the article JSON file

        Returns:
            bool: True if already indexed
        """
        key = self._normalize_path(file_path)
        return key in self._indexed

    def is_failed(self, file_path: str | Path) -> bool:
        """
        Check if a file previously failed to index.

        Args:
            file_path: Path to the article JSON file

        Returns:
            bool: True if previously failed
        """
        key = self._normalize_path(file_path)
        return key in self._failed

    def mark_indexed(
            self,
            file_path: str | Path,
            article_id: str,
            chunks: int,
    ) -> None:
        """
        Mark a file as successfully indexed.

        Args:
            file_path: Path to the article JSON file
            article_id: The article's unique ID
            chunks: Number of chunks indexed
        """
        key = self._normalize_path(file_path)
        self._indexed[key] = {
            "article_id": article_id,
            "chunks": chunks,
            "indexed_at": datetime.utcnow().isoformat(),
        }
        # Remove from failed if it was there
        self._failed.pop(key, None)
        self._dirty = True

    def mark_failed(self, file_path: str | Path, error: str) -> None:
        """
        Mark a file as failed to index.

        Args:
            file_path: Path to the article JSON file
            error: Error message describing the failure
        """
        key = self._normalize_path(file_path)
        self._failed[key] = {
            "error": error,
            "failed_at": datetime.utcnow().isoformat(),
        }
        self._dirty = True

    def get_indexed_info(self, file_path: str | Path) -> Optional[dict]:
        """Get indexing info for a file."""
        key = self._normalize_path(file_path)
        return self._indexed.get(key)

    def get_failed_info(self, file_path: str | Path) -> Optional[dict]:
        """Get failure info for a file."""
        key = self._normalize_path(file_path)
        return self._failed.get(key)

    def get_pending_files(
            self,
            articles_dir: str | Path,
            include_failed: bool = False,
    ) -> list[Path]:
        """
        Get list of files that haven't been indexed yet.

        Args:
            articles_dir: Root directory containing article JSON files
            include_failed: Whether to include previously failed files

        Returns:
            list[Path]: Paths to pending files
        """
        articles_dir = Path(articles_dir)
        all_files = list(articles_dir.rglob("*.json"))

        pending = []
        for file_path in all_files:
            if self.is_indexed(file_path):
                continue
            if not include_failed and self.is_failed(file_path):
                continue
            pending.append(file_path)

        return sorted(pending)

    def clear_failed(self) -> int:
        """
        Clear all failed entries to allow retry.

        Returns:
            int: Number of cleared entries
        """
        count = len(self._failed)
        self._failed.clear()
        self._dirty = True
        return count

    @property
    def indexed_count(self) -> int:
        """Number of successfully indexed files."""
        return len(self._indexed)

    @property
    def failed_count(self) -> int:
        """Number of failed files."""
        return len(self._failed)

    @property
    def total_chunks(self) -> int:
        """Total number of chunks indexed."""
        return sum(info.get("chunks", 0) for info in self._indexed.values())

    def get_stats(self) -> dict:
        """
        Get indexing statistics.

        Returns:
            dict: Statistics about indexed and failed files
        """
        return {
            "indexed_files": self.indexed_count,
            "failed_files": self.failed_count,
            "total_chunks": self.total_chunks,
        }
