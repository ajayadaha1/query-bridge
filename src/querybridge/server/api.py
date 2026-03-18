"""FastAPI server — REST API endpoint for QueryBridge."""

import logging
import os
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger("querybridge.server.api")

# Lazy engine singleton
_engine: Any = None


def _get_engine() -> Any:
    global _engine
    if _engine is None:
        raise RuntimeError(
            "Engine not initialized. Call init_engine() or set environment variables."
        )
    return _engine


def init_engine(engine: Any):
    """Set the global engine instance for the API server."""
    global _engine
    _engine = engine


def create_app(engine: Any = None) -> Any:
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
        # Auto-initialize engine from environment variables
        global _engine
        if _engine is None:
            dsn = os.getenv("QUERYBRIDGE_DSN")
            api_key = os.getenv("QUERYBRIDGE_API_KEY")
            if dsn and api_key:
                from querybridge.core.config import EngineConfig
                from querybridge.core.engine import QueryBridgeEngine
                from querybridge.llm.openai_provider import OpenAIProvider

                provider = os.getenv("QUERYBRIDGE_PROVIDER", "openai")
                model = os.getenv("QUERYBRIDGE_MODEL", "gpt-4o")
                base_url = os.getenv("QUERYBRIDGE_BASE_URL")

                if "sqlite" in dsn:
                    from querybridge.connectors.sqlite import SQLiteConnector
                    connector = SQLiteConnector(dsn.replace("sqlite:///", ""))
                else:
                    from querybridge.connectors.postgresql import PostgreSQLConnector
                    connector = PostgreSQLConnector(dsn)

                if provider == "anthropic":
                    from querybridge.llm.anthropic_provider import AnthropicProvider
                    llm = AnthropicProvider(api_key=api_key, model=model)
                elif provider == "litellm":
                    from querybridge.llm.litellm_provider import LiteLLMProvider
                    llm = LiteLLMProvider(model=model, api_key=api_key)
                else:
                    # AMD LLM Gateway uses Ocp-Apim-Subscription-Key header
                    extra_kwargs: dict[str, Any] = {}
                    if base_url and "amd.com" in base_url:
                        extra_kwargs["default_headers"] = {
                            "Ocp-Apim-Subscription-Key": api_key,
                        }
                        extra_kwargs["api_key"] = "dummy"
                    else:
                        extra_kwargs["api_key"] = api_key
                    llm = OpenAIProvider(
                        model=model, base_url=base_url, **extra_kwargs
                    )

                _engine = QueryBridgeEngine(
                    connector=connector,
                    llm=llm,
                    config=EngineConfig(),
                )
                logger.info(f"Engine auto-initialized: {provider}/{model} → {dsn.split('@')[-1] if '@' in dsn else dsn}")
            else:
                logger.warning("QUERYBRIDGE_DSN or QUERYBRIDGE_API_KEY not set — engine not initialized")
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
        answer: str
        chat_id: str
        queries_executed: int
        query_log: list[dict[str, Any]]
        total_time_ms: int
        last_sql: str | None = None
        thinking_steps: list[dict[str, Any]] = []
        confidence: float = 0.0
        iterations_used: int = 0

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(body: ChatRequest):
        engine = _get_engine()
        response = await engine.query(
            question=body.message,
            chat_id=body.chat_id,
            history=body.history,
        )
        return ChatResponse(
            answer=response.answer,
            chat_id=response.chat_id,
            queries_executed=len(response.query_log),
            query_log=response.query_log,
            total_time_ms=response.total_time_ms,
            last_sql=response.last_sql,
            thinking_steps=response.thinking_steps,
            confidence=response.confidence,
            iterations_used=response.iterations_used,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "engine_ready": _engine is not None}

    return app


# Module-level app instance for `uvicorn querybridge.server.api:app`
app = create_app()
