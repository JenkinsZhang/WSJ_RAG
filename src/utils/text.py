"""
Text processing utilities for WSJ RAG system.

Provides text chunking with sentence boundary awareness,
optimized for news article processing.

Design Considerations:
    - Preserves semantic coherence by respecting sentence boundaries
    - Configurable overlap for context continuity in RAG
    - Character-based chunking with token estimation
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Character to token ratio (approximate)
# English: ~4 chars/token, Chinese: ~1.5 chars/token
# Using conservative estimate for mixed content
CHARS_PER_TOKEN = 4


@dataclass
class TextChunker:
    """
    Text chunker with sentence boundary awareness.

    Splits text into overlapping chunks while trying to
    preserve sentence boundaries for better semantic coherence.

    Attributes:
        chunk_size: Target chunk size in tokens
        chunk_overlap: Overlap between chunks in tokens

    Example:
        >>> chunker = TextChunker(chunk_size=512, chunk_overlap=50)
        >>> chunks = chunker.chunk_text(long_article)
        >>> print(f"Created {len(chunks)} chunks")
    """
    chunk_size: int = 512
    chunk_overlap: int = 50

    def chunk_text(
        self,
        text: str,
        chunk_size: Optional[int] = None,
        chunk_overlap: Optional[int] = None,
    ) -> list[str]:
        """
        Split text into overlapping chunks.

        Attempts to split at sentence boundaries when possible,
        falling back to hard splits for very long sentences.

        Args:
            text: Text to split
            chunk_size: Override default chunk size (tokens)
            chunk_overlap: Override default overlap (tokens)

        Returns:
            list[str]: Text chunks

        Note:
            Token counts are estimated using character ratio.
            For precise counts, use tiktoken or similar.
        """
        if not text or not text.strip():
            return []

        # Convert token targets to character counts
        char_chunk_size = (chunk_size or self.chunk_size) * CHARS_PER_TOKEN
        char_overlap = (chunk_overlap or self.chunk_overlap) * CHARS_PER_TOKEN

        # Split into sentences
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        chunks = []
        current_chunk: list[str] = []
        current_length = 0

        for sentence in sentences:
            sentence_len = len(sentence)

            # Handle sentences exceeding chunk size
            if sentence_len > char_chunk_size:
                # Flush current chunk first
                if current_chunk:
                    chunks.append(" ".join(current_chunk))
                    current_chunk = []
                    current_length = 0

                # Hard split the long sentence
                chunks.extend(self._hard_split(sentence, char_chunk_size, char_overlap))
                continue

            # Check if adding sentence exceeds limit
            if current_length + sentence_len > char_chunk_size and current_chunk:
                # Save current chunk
                chunks.append(" ".join(current_chunk))

                # Calculate overlap - keep sentences from end
                current_chunk, current_length = self._calculate_overlap(
                    current_chunk, char_overlap
                )

            current_chunk.append(sentence)
            current_length += sentence_len + 1  # +1 for space

        # Don't forget the last chunk
        if current_chunk:
            chunks.append(" ".join(current_chunk))

        logger.debug(f"Split text ({len(text)} chars) into {len(chunks)} chunks")
        return chunks

    def _split_sentences(self, text: str) -> list[str]:
        """
        Split text into sentences.

        Handles common sentence-ending punctuation for both
        English and Chinese text.

        Args:
            text: Text to split

        Returns:
            list[str]: Individual sentences
        """
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text.strip())

        # Split on sentence boundaries
        # Handles: . ! ? and Chinese 。！？
        sentences = re.split(r'(?<=[.!?。！？])\s+', text)

        return [s.strip() for s in sentences if s.strip()]

    def _hard_split(
        self,
        text: str,
        chunk_size: int,
        overlap: int,
    ) -> list[str]:
        """
        Split text by fixed character count.

        Used when sentences are too long to fit in a single chunk.

        Args:
            text: Text to split
            chunk_size: Maximum chunk size in characters
            overlap: Overlap in characters

        Returns:
            list[str]: Fixed-size chunks
        """
        chunks = []
        step = chunk_size - overlap

        for i in range(0, len(text), step):
            chunk = text[i:i + chunk_size]
            if chunk:
                chunks.append(chunk)

        return chunks

    def _calculate_overlap(
        self,
        sentences: list[str],
        target_overlap: int,
    ) -> tuple[list[str], int]:
        """
        Calculate sentences to keep for overlap.

        Keeps sentences from the end of the previous chunk
        to provide context continuity.

        Args:
            sentences: Sentences from previous chunk
            target_overlap: Target overlap in characters

        Returns:
            tuple: (overlap_sentences, total_length)
        """
        if not sentences:
            return [], 0

        overlap_sentences = []
        overlap_len = 0

        for sentence in reversed(sentences):
            if overlap_len + len(sentence) <= target_overlap:
                overlap_sentences.insert(0, sentence)
                overlap_len += len(sentence) + 1
            else:
                break

        return overlap_sentences, overlap_len


def estimate_token_count(text: str) -> int:
    """
    Estimate token count for text.

    Uses character-based estimation. For accurate counts,
    use tiktoken with the appropriate model encoding.

    Args:
        text: Text to estimate

    Returns:
        int: Estimated token count
    """
    if not text:
        return 0
    return len(text) // CHARS_PER_TOKEN


def truncate_text(text: str, max_tokens: int) -> str:
    """
    Truncate text to approximate token limit.

    Args:
        text: Text to truncate
        max_tokens: Maximum tokens

    Returns:
        str: Truncated text with ellipsis if needed
    """
    if not text:
        return text

    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(text) <= max_chars:
        return text

    return text[:max_chars - 3] + "..."
