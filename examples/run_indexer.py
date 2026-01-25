"""
Run the article indexer to index crawled articles into OpenSearch.

Usage:
    # Index all pending articles
    python -m examples.run_indexer

    # Index with retry of failed files
    python -m examples.run_indexer --retry-failed

    # Index specific category
    python -m examples.run_indexer --category tech

    # Dry run (show pending files without indexing)
    python -m examples.run_indexer --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.indexer import IndexPipeline, IndexState
from src.clients.opensearch import get_opensearch_client


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Quiet down noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("opensearch").setLevel(logging.WARNING)


def check_services() -> bool:
    """Check if required services are available."""
    print("Checking services...")

    # Check OpenSearch
    try:
        client = get_opensearch_client()
        health = client.health_check()
        if health.get("status") != "healthy":
            print(f"  OpenSearch: UNHEALTHY - {health}")
            return False
        print(f"  OpenSearch: OK (index exists: {client.index_exists()})")
    except Exception as e:
        print(f"  OpenSearch: ERROR - {e}")
        return False

    # Check Embedding service
    try:
        from src.clients.embedding import get_embedding_service
        embed_svc = get_embedding_service()
        health = embed_svc.health_check()
        if health.get("status") != "healthy":
            print(f"  Embedding: UNHEALTHY - {health}")
            return False
        print(f"  Embedding: OK ({embed_svc.model})")
    except Exception as e:
        print(f"  Embedding: ERROR - {e}")
        return False

    # Check LLM service
    try:
        from src.clients.llm import get_llm_service
        llm_svc = get_llm_service()
        health = llm_svc.health_check()
        if health.get("status") != "healthy":
            print(f"  LLM: UNHEALTHY - {health}")
            return False
        print(f"  LLM: OK (Bedrock)")
    except Exception as e:
        print(f"  LLM: ERROR - {e}")
        return False

    print()
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Index crawled articles into OpenSearch"
    )
    parser.add_argument(
        "--articles-dir",
        default="articles",
        help="Directory containing article JSON files (default: articles)",
    )
    parser.add_argument(
        "--category",
        help="Only index specific category (e.g., tech, finance)",
    )
    parser.add_argument(
        "--retry-failed",
        action="store_true",
        help="Retry previously failed files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show pending files without indexing",
    )
    parser.add_argument(
        "--clear-failed",
        action="store_true",
        help="Clear all failed entries and exit",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Show indexing statistics and exit",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    parser.add_argument(
        "--skip-check",
        action="store_true",
        help="Skip service health checks",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Determine articles directory
    articles_dir = Path(args.articles_dir)
    if args.category:
        articles_dir = articles_dir / args.category

    if not articles_dir.exists():
        print(f"Error: Directory not found: {articles_dir}")
        sys.exit(1)

    # Initialize state
    state = IndexState("data/indexed_files.json")

    # Handle stats command
    if args.stats:
        stats = state.get_stats()
        print("Indexing Statistics:")
        print(f"  Indexed files: {stats['indexed_files']}")
        print(f"  Failed files:  {stats['failed_files']}")
        print(f"  Total chunks:  {stats['total_chunks']}")
        return

    # Handle clear-failed command
    if args.clear_failed:
        count = state.clear_failed()
        state.save()
        print(f"Cleared {count} failed entries")
        return

    # Get pending files
    pending = state.get_pending_files(articles_dir, include_failed=args.retry_failed)
    print(f"Found {len(pending)} pending files in {articles_dir}")

    if not pending:
        print("Nothing to index.")
        return

    # Dry run - just show files
    if args.dry_run:
        print("\nPending files:")
        for i, f in enumerate(pending[:20], 1):
            print(f"  {i}. {f}")
        if len(pending) > 20:
            print(f"  ... and {len(pending) - 20} more")
        return

    # Check services before indexing
    if not args.skip_check:
        if not check_services():
            print("Service check failed. Use --skip-check to bypass.")
            sys.exit(1)

    # Ensure index exists and schema is current
    client = get_opensearch_client()
    schema_result = client.ensure_schema_current()
    if schema_result["status"] == "created":
        print(f"Created OpenSearch index: {schema_result['index']}")
    elif schema_result["status"] == "updated":
        print(f"Updated schema, added fields: {schema_result['fields_added']}")

    # Run indexer
    print(f"\nStarting indexer for {len(pending)} files...")
    print("-" * 50)

    pipeline = IndexPipeline(state_file="data/indexed_files.json")
    result = pipeline.index_all(articles_dir, include_failed=args.retry_failed)

    # Print summary
    print("-" * 50)
    print("\nIndexing Summary:")
    print(f"  Total files:   {result.total_files}")
    print(f"  Indexed:       {result.indexed}")
    print(f"  Skipped:       {result.skipped}")
    print(f"  Failed:        {result.failed}")
    print(f"  Total chunks:  {result.total_chunks}")
    print(f"  Elapsed time:  {result.elapsed_seconds:.1f}s")

    if result.indexed > 0:
        avg_time = result.elapsed_seconds / result.indexed
        print(f"  Avg per file:  {avg_time:.1f}s")

    # Show failed files if any
    if result.failed > 0:
        print(f"\nFailed files ({result.failed}):")
        for r in result.results:
            if not r.success:
                print(f"  - {r.file_path}: {r.error}")


if __name__ == "__main__":
    main()
