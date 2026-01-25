"""
WSJ RAG API Server

FastAPI application providing REST endpoints for:
    - Health checks
    - News article indexing
    - Semantic and hybrid search
    - Recent news retrieval

Usage:
    uvicorn main:app --reload
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from src.config import get_settings
from src.models import NewsArticle
from src.storage import OpenSearchClient, NewsRepository
from src.services import EmbeddingService, LLMService

# ===== Application Setup =====

app = FastAPI(
    title="WSJ RAG API",
    description="News RAG system with semantic search capabilities",
    version="1.0.0",
)

# Lazy-loaded services
_os_client: Optional[OpenSearchClient] = None
_embedding_svc: Optional[EmbeddingService] = None
_llm_svc: Optional[LLMService] = None
_repo: Optional[NewsRepository] = None


def get_services():
    """Initialize and return service instances."""
    global _os_client, _embedding_svc, _llm_svc, _repo

    if _os_client is None:
        _os_client = OpenSearchClient()
        _embedding_svc = EmbeddingService()
        _llm_svc = LLMService()
        _repo = NewsRepository(_os_client)

    return _os_client, _embedding_svc, _llm_svc, _repo


# ===== Request/Response Models =====

class ArticleRequest(BaseModel):
    """Request model for indexing articles."""
    title: str
    content: str
    url: str
    source: str = "WSJ"
    category: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[datetime] = None


class SearchRequest(BaseModel):
    """Request model for search queries."""
    query: str
    k: int = 5
    use_hybrid: bool = True


class HealthResponse(BaseModel):
    """Response model for health check."""
    status: str
    opensearch: dict
    embedding: dict
    llm: dict


# ===== API Endpoints =====

@app.get("/")
async def root():
    """Root endpoint with API information."""
    return {
        "name": "WSJ RAG API",
        "version": "1.0.0",
        "docs": "/docs",
    }


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Check health of all services."""
    os_client, embedding_svc, llm_svc, _ = get_services()

    return HealthResponse(
        status="ok",
        opensearch=os_client.health_check(),
        embedding=embedding_svc.health_check(),
        llm=llm_svc.health_check(),
    )


@app.post("/index/setup")
async def setup_index(recreate: bool = False):
    """Create or recreate the OpenSearch index."""
    os_client, _, _, _ = get_services()
    result = os_client.ensure_index_exists(recreate=recreate)
    return result


@app.post("/articles")
async def index_article(request: ArticleRequest, skip_summary: bool = False):
    """
    Index a news article.

    Processes the article (chunking, embedding, optional summarization)
    and indexes to OpenSearch.
    """
    os_client, embedding_svc, llm_svc, repo = get_services()

    # Ensure index exists
    os_client.ensure_index_exists()

    # Create article model
    article = NewsArticle(
        title=request.title,
        content=request.content,
        url=request.url,
        source=request.source,
        category=request.category,
        author=request.author,
        published_at=request.published_at,
    )

    # Process and index
    processed = embedding_svc.process_document(
        article,
        llm_service=None if skip_summary else llm_svc,
    )
    responses = repo.index_document(processed)

    return {
        "status": "indexed",
        "article_id": processed.generate_id(),
        "chunks_indexed": len(responses),
        "article_summary": processed.article_summary,
    }


@app.post("/search")
async def search(request: SearchRequest):
    """
    Search for relevant news chunks.

    Supports both pure vector search and hybrid search.
    """
    _, embedding_svc, _, repo = get_services()

    # Generate query embedding
    query_vector = embedding_svc.embed_text(request.query)

    # Perform search
    if request.use_hybrid:
        results = repo.hybrid_search(
            query_text=request.query,
            query_vector=query_vector,
            k=request.k,
        )
    else:
        results = repo.search_by_vector(
            query_vector=query_vector,
            k=request.k,
        )

    return {
        "query": request.query,
        "results": [
            {
                "title": r.title,
                "content": r.content,
                "chunk_summary": r.chunk_summary,
                "article_summary": r.article_summary,
                "url": r.url,
                "score": r.score,
                "category": r.category,
            }
            for r in results
        ],
    }


@app.get("/news/recent")
async def get_recent_news(hours: int = 24, limit: int = 20, category: Optional[str] = None):
    """Get recent news articles."""
    _, _, _, repo = get_services()

    results = repo.get_recent_news(hours=hours, limit=limit, category=category)

    return {
        "timeframe_hours": hours,
        "count": len(results),
        "articles": [
            {
                "title": r.title,
                "article_summary": r.article_summary,
                "url": r.url,
                "category": r.category,
                "published_at": r.published_at,
            }
            for r in results
        ],
    }


@app.get("/stats")
async def get_stats():
    """Get index statistics."""
    os_client, _, _, repo = get_services()

    stats = os_client.get_index_stats()
    doc_count = repo.count_documents()

    return {
        "index": stats.get("index"),
        "document_count": doc_count,
        "size_bytes": stats.get("size_bytes", 0),
    }
