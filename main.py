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

import asyncio

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, AsyncGenerator
from datetime import datetime
import logging
import json

# Configure application logging (uvicorn only handles its own loggers)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("opensearch").setLevel(logging.WARNING)
logging.getLogger("botocore").setLevel(logging.WARNING)
logging.getLogger("boto3").setLevel(logging.WARNING)

from src.config import get_settings
from src.models import NewsArticle
from src.storage.repository import NewsRepository
from src.clients import OpenSearchClient, EmbeddingService, LLMService
from src.agent.news_agent import NewsAgent
from src.agent.session import get_session_manager

logger = logging.getLogger(__name__)

# ===== Application Setup =====

app = FastAPI(
    title="WSJ RAG API",
    description="News RAG system with semantic search capabilities",
    version="1.0.0",
)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def startup_session_cleanup():
    """Start background task to clean up expired sessions."""
    async def cleanup_loop():
        while True:
            await asyncio.sleep(300)  # Every 5 minutes
            get_session_manager().cleanup_expired()
    asyncio.create_task(cleanup_loop())


# Lazy-loaded services
_os_client: Optional[OpenSearchClient] = None
_embedding_svc: Optional[EmbeddingService] = None
_llm_svc: Optional[LLMService] = None
_repo: Optional[NewsRepository] = None
_news_agent: Optional[NewsAgent] = None


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


# ===== Chat Endpoint =====

def get_agent() -> NewsAgent:
    """Get or create NewsAgent singleton."""
    global _news_agent
    if _news_agent is None:
        _news_agent = NewsAgent(verbose=False)
    return _news_agent


class ChatRequest(BaseModel):
    """Request model for chat."""
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    """Response model for chat."""
    response: str
    session_id: str
    message_id: Optional[str] = None


class FeedbackRequest(BaseModel):
    """Request model for feedback."""
    session_id: str
    message_id: str
    rating: int  # 1-5
    comment: Optional[str] = None


class SessionResponse(BaseModel):
    """Response model for session creation."""
    session_id: str


@app.post("/session", response_model=SessionResponse)
async def create_session():
    """Create a new chat session."""
    manager = get_session_manager()
    session = manager.create_session()
    return SessionResponse(session_id=session.session_id)


@app.delete("/session/{session_id}")
async def delete_session(session_id: str):
    """Delete a chat session."""
    manager = get_session_manager()
    deleted = manager.delete_session(session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"status": "deleted"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Chat with the news agent, with optional session for multi-turn."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")
    try:
        agent = get_agent()
        manager = get_session_manager()
        session = manager.get_or_create(request.session_id)
        response = await agent.chat(request.message, session=session)
        last_msg = session.messages[-1] if session.messages else None
        return ChatResponse(
            response=response,
            session_id=session.session_id,
            message_id=last_msg.message_id if last_msg else None,
        )
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=f"Chat failed: {str(e)}")


async def generate_sse_events(message: str, session_id: Optional[str] = None) -> AsyncGenerator[str, None]:
    """Generate Server-Sent Events for streaming chat."""
    agent = get_agent()
    manager = get_session_manager()
    session = manager.get_or_create(session_id)

    # Send session_id as first event
    yield f"data: {json.dumps({'type': 'session', 'session_id': session.session_id}, ensure_ascii=False)}\n\n"

    async for event in agent.chat_stream(message, session=session):
        yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Stream chat with SSE, with optional session for multi-turn."""
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    return StreamingResponse(
        generate_sse_events(request.message, request.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


@app.post("/chat/feedback")
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback on an assistant message."""
    if not 1 <= request.rating <= 5:
        raise HTTPException(status_code=400, detail="Rating must be 1-5")
    manager = get_session_manager()
    session = manager.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found or expired")
    session.add_feedback(request.message_id, request.rating, request.comment)
    return {"status": "ok"}


# ===== Static File Serving =====

@app.get("/chat-ui")
async def chat_ui():
    """Serve the chat UI page."""
    return FileResponse("static/chat.html")
