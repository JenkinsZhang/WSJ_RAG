"""
Progress tracking for agent tools.

Provides a mechanism to emit progress events from within tool execution,
which can be captured by the streaming chat interface.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Callable, Any
from enum import Enum

logger = logging.getLogger(__name__)


class ProgressStep(str, Enum):
    """Types of progress steps."""
    ANALYZING = "analyzing"
    EMBEDDING = "embedding"
    SEARCHING = "searching"
    SUMMARIZING = "summarizing"
    PROCESSING = "processing"
    EVALUATING = "evaluating"


@dataclass
class ProgressEvent:
    """A progress event from tool execution."""
    step: str
    content: str
    detail: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        return {
            "type": "tool_progress",
            "step": self.step,
            "content": self.content,
            "detail": self.detail,
            "timestamp": self.timestamp.isoformat(),
        }


class ProgressTracker:
    """
    Thread-safe progress tracker that collects events during tool execution.

    Usage:
        tracker = ProgressTracker()
        set_progress_tracker(tracker)

        # In tool code:
        emit_progress("analyzing", "分析查询意图...")

        # To get events:
        events = tracker.get_new_events()
    """

    def __init__(self):
        self._events: List[ProgressEvent] = []
        self._lock = threading.Lock()
        self._read_index = 0
        self._queue: Optional[asyncio.Queue] = None

    def set_queue(self, queue: asyncio.Queue):
        """Set an async queue for real-time event delivery."""
        self._queue = queue

    def emit(self, step: str, content: str, detail: Optional[str] = None):
        """Emit a progress event."""
        event = ProgressEvent(step=step, content=content, detail=detail)

        with self._lock:
            self._events.append(event)

        # Try to put in queue for real-time delivery
        if self._queue:
            try:
                self._queue.put_nowait(event.to_dict())
            except Exception as e:
                logger.debug(f"Failed to put event in queue: {e}")

    def get_new_events(self) -> List[ProgressEvent]:
        """Get events that haven't been read yet."""
        with self._lock:
            new_events = self._events[self._read_index:]
            self._read_index = len(self._events)
            return new_events

    def get_all_events(self) -> List[ProgressEvent]:
        """Get all events."""
        with self._lock:
            return list(self._events)

    def clear(self):
        """Clear all events."""
        with self._lock:
            self._events.clear()
            self._read_index = 0


# Context variable for the current progress tracker
_progress_tracker: ContextVar[Optional[ProgressTracker]] = ContextVar(
    'progress_tracker', default=None
)

# Fallback global tracker for cases where context doesn't propagate
_global_tracker: Optional[ProgressTracker] = None
_global_lock = threading.Lock()


def set_progress_tracker(tracker: Optional[ProgressTracker]):
    """Set the progress tracker for the current context."""
    global _global_tracker
    _progress_tracker.set(tracker)
    with _global_lock:
        _global_tracker = tracker


def get_progress_tracker() -> Optional[ProgressTracker]:
    """Get the current progress tracker."""
    # Try context var first
    tracker = _progress_tracker.get()
    if tracker:
        return tracker
    # Fallback to global
    with _global_lock:
        return _global_tracker


def emit_progress(step: str, content: str, detail: Optional[str] = None):
    """
    Emit a progress event from within tool execution.

    Args:
        step: The type of step (e.g., "analyzing", "embedding", "searching")
        content: Human-readable description of what's happening
        detail: Optional additional detail (e.g., the query being analyzed)
    """
    tracker = get_progress_tracker()
    if tracker:
        tracker.emit(step, content, detail)
        logger.debug(f"Progress: [{step}] {content}")
    else:
        logger.debug(f"No tracker, skipping progress: [{step}] {content}")


# Convenience functions for common steps
def emit_analyzing(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.ANALYZING, content, detail)


def emit_embedding(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.EMBEDDING, content, detail)


def emit_searching(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.SEARCHING, content, detail)


def emit_summarizing(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.SUMMARIZING, content, detail)


def emit_processing(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.PROCESSING, content, detail)


def emit_evaluating(content: str, detail: Optional[str] = None):
    emit_progress(ProgressStep.EVALUATING, content, detail)
