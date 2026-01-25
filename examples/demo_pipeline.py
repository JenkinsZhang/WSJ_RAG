"""
Demo script showing the complete RAG pipeline.

This script demonstrates:
    1. Creating an article
    2. Processing with embeddings and summaries
    3. Indexing to OpenSearch
    4. Searching by vector similarity

Usage:
    python -m examples.demo_pipeline

Requirements:
    - LM Studio running with qwen3-embedding-8b loaded
    - OpenSearch running on localhost:9200
    - AWS credentials configured for Bedrock
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from datetime import datetime

from src.config import get_settings
from src.models import NewsArticle
from src.storage import NewsRepository
from src.clients import OpenSearchClient, EmbeddingService, LLMService


def main():
    """Run the demo pipeline."""
    print("=" * 60)
    print("WSJ RAG Demo Pipeline")
    print("=" * 60)

    # Initialize services
    print("\n[1/6] Initializing services...")
    settings = get_settings()
    print(f"  OpenSearch: {settings.opensearch.host}:{settings.opensearch.port}")
    print(f"  Embedding model: {settings.embedding.model}")
    print(f"  LLM model: {settings.llm.model_id}")

    os_client = OpenSearchClient()
    embedding_svc = EmbeddingService()
    llm_svc = LLMService()
    repo = NewsRepository(os_client)

    # Health checks
    print("\n[2/6] Running health checks...")

    os_health = os_client.health_check()
    print(f"  OpenSearch: {os_health['status']}")
    if os_health["status"] != "healthy":
        print(f"    Error: {os_health.get('error')}")
        return

    embed_health = embedding_svc.health_check()
    print(f"  Embedding: {embed_health['status']}")
    if embed_health["status"] != "healthy":
        print(f"    Error: {embed_health.get('error')}")
        return

    llm_health = llm_svc.health_check()
    print(f"  LLM: {llm_health['status']}")
    if llm_health["status"] != "healthy":
        print(f"    Error: {llm_health.get('error')}")
        print("    (Continuing without LLM summarization)")
        llm_svc = None

    # Ensure index exists
    print("\n[3/6] Ensuring index exists...")
    result = os_client.ensure_index_exists()
    print(f"  Index '{os_client.schema.index_name}': {result['status']}")

    # Create sample article
    print("\n[4/6] Creating sample article...")
    article = NewsArticle(
        title="Federal Reserve Holds Interest Rates Steady Amid Inflation Concerns",
        content="""
        The Federal Reserve announced Wednesday that it would maintain interest rates
        at their current levels of 5.25% to 5.5%, citing ongoing concerns about inflation.

        Fed Chair Jerome Powell stated that the committee remains committed to bringing
        inflation back to its 2% target. "We need to see more evidence that inflation
        is moving sustainably toward our goal before we can consider adjusting rates,"
        Powell said at a press conference following the decision.

        Markets reacted positively to the news, with the S&P 500 rising 1.2% in afternoon
        trading. The decision was widely expected by investors, who had been closely
        watching economic indicators for signs of cooling inflation.

        The labor market remains strong, with unemployment at historically low levels.
        However, consumer spending has shown signs of slowing in recent months,
        particularly in discretionary categories.

        Looking ahead, the Fed indicated it would continue to monitor economic data
        closely before making any changes to monetary policy. Most analysts expect
        rates to remain unchanged through at least the first quarter of next year.

        The decision marks the fourth consecutive meeting where the Fed has held rates
        steady, following a series of aggressive rate hikes over the past two years
        aimed at combating the highest inflation in four decades.
        """,
        url="https://wsj.com/articles/fed-holds-rates-steady-2024-demo",
        source="WSJ",
        category="Markets",
        author="Demo Author",
        published_at=datetime.now(),
    )
    print(f"  Title: {article.title}")
    print(f"  Content length: {len(article.content)} chars")

    # Process article
    print("\n[5/6] Processing article...")
    print("  - Chunking content")
    print("  - Generating embeddings")
    if llm_svc:
        print("  - Generating summaries")

    processed = embedding_svc.process_document(article, llm_svc)
    print(f"  Chunks created: {processed.chunk_count}")
    print(f"  Article summary: {processed.article_summary[:100]}..." if processed.article_summary else "  Article summary: (none)")

    # Index document
    print("\n[6/6] Indexing to OpenSearch...")
    responses = repo.index_document(processed)
    print(f"  Indexed {len(responses)} chunks")

    # Demo search
    print("\n" + "=" * 60)
    print("Demo Search")
    print("=" * 60)

    query = "What did the Federal Reserve decide about interest rates?"
    print(f"\nQuery: {query}")

    # Generate query embedding
    query_vector = embedding_svc.embed_text(query)

    # Search
    results = repo.search_by_vector(query_vector, k=3)
    print(f"\nFound {len(results)} results:")
    for i, result in enumerate(results, 1):
        print(f"\n[{i}] Score: {result.score:.4f}")
        print(f"    Title: {result.title}")
        print(f"    Chunk {result.chunk_index}: {result.content[:150]}...")
        if result.chunk_summary:
            print(f"    Summary: {result.chunk_summary}")

    # Stats
    print("\n" + "=" * 60)
    print("Index Statistics")
    print("=" * 60)
    stats = os_client.get_index_stats()
    print(f"  Documents: {stats.get('doc_count', 0)}")
    print(f"  Size: {stats.get('size_bytes', 0) / 1024:.2f} KB")

    print("\nDemo completed!")


if __name__ == "__main__":
    main()
