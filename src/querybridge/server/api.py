"""FastAPI server — REST API endpoint for QueryBridge."""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from querybridge.core.engine import QueryBridgeEngine

logger = logging.getLogger("querybridge.server.api")

# Lazy engine singleton
_engine: QueryBridgeEngine | None = None


def _get_engine() -> QueryBridgeEngine:
    global _engine
    if _engine is None:
        raise RuntimeError(
            "Engine not initialized. Call init_engine() or set environment variables."
        )
    return _engine


def init_engine(engine: QueryBridgeEngine):
    """Set the global engine instance for the API server."""
    global _engine
    _engine = engine


def create_app(engine: QueryBridgeEngine | None = None) -> Any:
    """Create and return a FastAPI application.

    If *engine* is provided, it will be used directly. Otherwise, the engine
    must be initialized separately via ``init_engine()`` before serving requests.
    """
    try:
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as err:
        raise ImportError(
            "FastAPI is required for API mode. "
            "Install with: pip install querybridge[server]"
        ) from err

    if engine:
        init_engine(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        if _engine:
            await _engine.close()

    app = FastAPI(
        title="QueryBridge",
        description="Natural Language to SQL API",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    class ChatRequest(BaseModel):
        message: str
        chat_id: str | None = None
        history: list[dict[str, Any]] | None = []

    class ChatResponse(BaseModel):
        success: bool
        answer: str
        chat_id: str
        queries_executed: int
        query_log: list[dict[str, Any]]
        total_time_ms: int
        last_sql: str | None = None
        thinking_steps: list[dict[str, Any]] = []
        confidence_score: float = 1.0
        validation_notes: list[str] = []

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(request: ChatRequest):
        engine = _get_engine()
        response = await engine.query(
            question=request.message,
            chat_id=request.chat_id,
            history=request.history,
        )
        return ChatResponse(
            success=response.success,
            answer=response.answer,
            chat_id=response.chat_id,
            queries_executed=response.queries_executed,
            query_log=[e.__dict__ if hasattr(e, "__dict__") else e for e in response.query_log],
            total_time_ms=response.total_time_ms,
            last_sql=response.last_sql,
            thinking_steps=response.thinking_steps,
            confidence_score=response.confidence_score,
            validation_notes=response.validation_notes,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "engine_ready": _engine is not None}

    return app
