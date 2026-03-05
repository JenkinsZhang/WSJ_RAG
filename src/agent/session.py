"""
In-memory session management for multi-turn conversations.

Provides ChatSession with message history, feedback tracking,
and a thread-safe ChatSessionManager with TTL-based expiration.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    """A single message in a chat session."""
    role: str  # "user" or "assistant"
    content: str
    message_id: str = field(default_factory=lambda: uuid4().hex[:12])
    timestamp: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)


@dataclass
class FeedbackEntry:
    """User feedback on a specific message."""
    message_id: str
    rating: int  # 1-5
    comment: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)


class ChatSession:
    """A single chat session with message history and feedback."""

    def __init__(self, session_id: str, max_messages: int = 50) -> None:
        self.session_id = session_id
        self.max_messages = max_messages
        self.created_at: datetime = datetime.now()
        self.last_active: datetime = datetime.now()
        self.messages: list[ChatMessage] = []
        self.feedback: list[FeedbackEntry] = []

    def add_message(self, role: str, content: str, metadata: Optional[dict] = None) -> ChatMessage:
        """Add a message to the session and return it."""
        message = ChatMessage(
            role=role,
            content=content,
            metadata=metadata or {},
        )
        self.messages.append(message)
        self.last_active = datetime.now()
        self._trim()
        return message

    def _trim(self) -> None:
        """Keep only the most recent max_messages."""
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def add_feedback(self, message_id: str, rating: int, comment: Optional[str] = None) -> None:
        """Record feedback for a message."""
        entry = FeedbackEntry(
            message_id=message_id,
            rating=rating,
            comment=comment,
        )
        self.feedback.append(entry)

    def get_history_for_prompt(self, max_turns: int = 10) -> list[dict]:
        """Return recent messages formatted for LLM prompt."""
        recent = self.messages[-(max_turns * 2):]
        return [{"role": m.role, "content": m.content} for m in recent]

    def get_recent_feedback_summary(self) -> Optional[str]:
        """Return formatted string of recent feedback (last 30min, max 3), or None."""
        cutoff = datetime.now() - timedelta(minutes=30)
        recent = [f for f in self.feedback if f.timestamp >= cutoff]
        if not recent:
            return None

        recent = recent[-3:]
        lines = []
        for entry in recent:
            line = f"- Rating: {entry.rating}/5"
            if entry.comment:
                line += f" — {entry.comment}"
            lines.append(line)
        return "Recent feedback:\n" + "\n".join(lines)


class ChatSessionManager:
    """Thread-safe manager for chat sessions with TTL-based expiration."""

    def __init__(self, ttl_minutes: int = 30) -> None:
        self._ttl_minutes = ttl_minutes
        self._sessions: dict[str, ChatSession] = {}
        self._lock = threading.Lock()

    def create_session(self) -> ChatSession:
        """Create a new chat session."""
        session_id = uuid4().hex[:16]
        session = ChatSession(session_id=session_id)
        with self._lock:
            self._sessions[session_id] = session
        logger.debug("Created session %s", session_id)
        return session

    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """Return session if it exists and is not expired, otherwise None."""
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                del self._sessions[session_id]
                logger.debug("Session %s expired", session_id)
                return None
            return session

    def get_or_create(self, session_id: Optional[str] = None) -> ChatSession:
        """Get an existing session or create a new one."""
        if session_id is not None:
            session = self.get_session(session_id)
            if session is not None:
                return session
        return self.create_session()

    def delete_session(self, session_id: str) -> bool:
        """Delete a session. Returns True if it existed."""
        with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                logger.debug("Deleted session %s", session_id)
                return True
            return False

    def cleanup_expired(self) -> int:
        """Remove expired sessions and return count removed."""
        with self._lock:
            expired = [
                sid for sid, session in self._sessions.items()
                if self._is_expired(session)
            ]
            for sid in expired:
                del self._sessions[sid]
        if expired:
            logger.info("Cleaned up %d expired sessions", len(expired))
        return len(expired)

    @property
    def active_count(self) -> int:
        """Number of active (non-expired) sessions."""
        with self._lock:
            return sum(
                1 for session in self._sessions.values()
                if not self._is_expired(session)
            )

    def _is_expired(self, session: ChatSession) -> bool:
        """Check if a session has exceeded its TTL."""
        return datetime.now() - session.last_active > timedelta(minutes=self._ttl_minutes)


# Singleton instance
_session_manager: Optional[ChatSessionManager] = None
_manager_lock = threading.Lock()


def get_session_manager() -> ChatSessionManager:
    """Get or create the singleton ChatSessionManager."""
    global _session_manager
    if _session_manager is None:
        with _manager_lock:
            if _session_manager is None:
                _session_manager = ChatSessionManager()
    return _session_manager
