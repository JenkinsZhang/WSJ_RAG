"""
Article indexing pipeline for WSJ RAG system.

Orchestrates the complete indexing workflow:
    1. Load articles from JSON files
    2. Convert to NewsArticle format
    3. Process with embeddings and LLM summaries
    4. Index into OpenSearch
    5. Track progress in state file
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from src.indexer.loader import ArticleLoader, get_article_loader
from src.indexer.state import IndexState
from src.services.embedding import EmbeddingService, get_embedding_service
from src.services.llm import LLMService, get_llm_service
from src.storage.client import get_opensearch_client
from src.storage.repository import NewsRepository

logger = logging.getLogger(__name__)


@dataclass
class IndexResult:
    """Result of indexing a single article."""
    file_path: str
    article_id: str
    title: str
    chunks: int
    elapsed_seconds: float
    success: bool
    error: Optional[str] = None


@dataclass
class BatchResult:
    """Result of batch indexing operation."""
    total_files: int
    indexed: int
    skipped: int
    failed: int
    total_chunks: int
    elapsed_seconds: float
    results: list[IndexResult] = field(default_factory=list)


class IndexPipeline:
    """
    Main indexing pipeline for articles.

    Coordinates loading, processing, and indexing of crawled articles
    with support for incremental updates and failure recovery.

    Example:
        >>> pipeline = IndexPipeline()
        >>> result = pipeline.index_all("articles/")
        >>> print(f"Indexed {result.indexed} articles with {result.total_chunks} chunks")
    """

    def __init__(
            self,
            embedding_service: Optional[EmbeddingService] = None,
            llm_service: Optional[LLMService] = None,
            repository: Optional[NewsRepository] = None,
            loader: Optional[ArticleLoader] = None,
            state_file: str | Path = "data/indexed_files.json",
    ) -> None:
        """
        Initialize the pipeline.

        Args:
            embedding_service: Optional embedding service (uses singleton if not provided)
            llm_service: Optional LLM service (uses singleton if not provided)
            repository: Optional repository (creates new if not provided)
            loader: Optional article loader (uses singleton if not provided)
            state_file: Path to the state tracking file
        """
        self._embedding_service = embedding_service
        self._llm_service = llm_service
        self._repository = repository
        self._loader = loader or get_article_loader()
        self._state = IndexState(state_file)

    @property
    def embedding_service(self) -> EmbeddingService:
        """Lazy-load embedding service."""
        if self._embedding_service is None:
            self._embedding_service = get_embedding_service()
        return self._embedding_service

    @property
    def llm_service(self) -> LLMService:
        """Lazy-load LLM service."""
        if self._llm_service is None:
            self._llm_service = get_llm_service()
        return self._llm_service

    @property
    def repository(self) -> NewsRepository:
        """Lazy-load repository."""
        if self._repository is None:
            self._repository = NewsRepository(get_opensearch_client())
        return self._repository

    def index_single(
            self,
            file_path: str | Path,
            skip_if_indexed: bool = True,
    ) -> IndexResult:
        """
        Index a single article file.

        Args:
            file_path: Path to the article JSON file
            skip_if_indexed: Whether to skip if already indexed

        Returns:
            IndexResult: Result of the indexing operation
        """
        file_path = Path(file_path)
        start_time = time.time()

        # Check if already indexed
        if skip_if_indexed and self._state.is_indexed(file_path):
            info = self._state.get_indexed_info(file_path)
            return IndexResult(
                file_path=str(file_path),
                article_id=info.get("article_id", ""),
                title="(skipped - already indexed)",
                chunks=info.get("chunks", 0),
                elapsed_seconds=0,
                success=True,
            )

        try:
            # Step 1: Load article
            article = self._loader.load_file(file_path)
            logger.info(f"Processing: {article.title}")

            # Step 2: Process with embeddings and summaries
            processed_doc = self.embedding_service.process_document(
                article, self.llm_service
            )

            # Step 3: Index to OpenSearch
            self.repository.index_document(processed_doc)

            # Step 4: Update state
            article_id = processed_doc.generate_id()
            self._state.mark_indexed(file_path, article_id, len(processed_doc.chunks))

            elapsed = time.time() - start_time
            logger.info(
                f"Indexed: {article.title} "
                f"({len(processed_doc.chunks)} chunks, {elapsed:.1f}s)"
            )

            return IndexResult(
                file_path=str(file_path),
                article_id=article_id,
                title=article.title,
                chunks=len(processed_doc.chunks),
                elapsed_seconds=elapsed,
                success=True,
            )

        except Exception as e:
            elapsed = time.time() - start_time
            error_msg = str(e)
            logger.error(f"Failed to index {file_path}: {error_msg}")
            self._state.mark_failed(file_path, error_msg)

            return IndexResult(
                file_path=str(file_path),
                article_id="",
                title="",
                chunks=0,
                elapsed_seconds=elapsed,
                success=False,
                error=error_msg,
            )

    def index_all(
            self,
            articles_dir: str | Path,
            include_failed: bool = False,
            save_interval: int = 5,
    ) -> BatchResult:
        """
        Index all pending articles from a directory.

        Args:
            articles_dir: Root directory containing article JSON files
            include_failed: Whether to retry previously failed files
            save_interval: Save state every N files

        Returns:
            BatchResult: Summary of the batch operation
        """
        articles_dir = Path(articles_dir)
        start_time = time.time()

        # Get pending files
        pending_files = self._state.get_pending_files(articles_dir, include_failed)
        total_files = len(pending_files)

        if total_files == 0:
            logger.info("No pending files to index")
            return BatchResult(
                total_files=0,
                indexed=0,
                skipped=0,
                failed=0,
                total_chunks=0,
                elapsed_seconds=0,
            )

        logger.info(f"Found {total_files} pending files to index")

        results = []
        indexed = 0
        skipped = 0
        failed = 0
        total_chunks = 0

        for i, file_path in enumerate(pending_files, 1):
            # Progress indicator
            logger.info(f"[{i}/{total_files}] Processing {file_path.name}")

            result = self.index_single(file_path, skip_if_indexed=True)
            results.append(result)

            if result.success:
                if result.title == "(skipped - already indexed)":
                    skipped += 1
                else:
                    indexed += 1
                    total_chunks += result.chunks
            else:
                failed += 1

            # Save state periodically
            if i % save_interval == 0:
                self._state.save()

        # Final save
        self._state.save()

        elapsed = time.time() - start_time
        logger.info(
            f"Batch complete: {indexed} indexed, {skipped} skipped, "
            f"{failed} failed in {elapsed:.1f}s"
        )

        return BatchResult(
            total_files=total_files,
            indexed=indexed,
            skipped=skipped,
            failed=failed,
            total_chunks=total_chunks,
            elapsed_seconds=elapsed,
            results=results,
        )

    # TODO: Implement batch processing with configurable batch_size
    # def index_batch(
    #     self,
    #     articles_dir: str | Path,
    #     batch_size: int = 10,
    # ) -> BatchResult:
    #     """
    #     Index articles in batches for better resource management.
    #     """
    #     pass

    def get_stats(self) -> dict:
        """
        Get indexing statistics.

        Returns:
            dict: Statistics including indexed/failed counts
        """
        return self._state.get_stats()

    def clear_failed(self) -> int:
        """
        Clear failed entries to allow retry.

        Returns:
            int: Number of cleared entries
        """
        count = self._state.clear_failed()
        self._state.save()
        logger.info(f"Cleared {count} failed entries")
        return count


# Module-level factory
def create_pipeline(state_file: str = "data/indexed_files.json") -> IndexPipeline:
    """
    Create a new IndexPipeline with default services.

    Args:
        state_file: Path to the state tracking file

    Returns:
        IndexPipeline: Configured pipeline instance
    """
    return IndexPipeline(state_file=state_file)
