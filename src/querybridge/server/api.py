"""FastAPI server — REST API endpoint for QueryBridge.

Supports multiple concurrent datasources with a default auto-configured
from environment variables. Datasources can be added/removed/toggled at
runtime via the /api/datasources endpoints.
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

logger = logging.getLogger("querybridge.server.api")

# ── Datasource registry ────────────────────────────────────────────────
# Each datasource: {id, name, type, dsn, active, default, engine}

_datasources: dict[str, dict[str, Any]] = {}
_llm: Any = None  # shared LLM provider

# LLM config — runtime-updatable via /api/llm
_llm_config: dict[str, str] = {
    "provider": os.getenv("QUERYBRIDGE_PROVIDER", "openai"),
    "api_key": os.getenv("QUERYBRIDGE_API_KEY", ""),
    "model": os.getenv("QUERYBRIDGE_MODEL", "gpt-4o"),
    "base_url": os.getenv("QUERYBRIDGE_BASE_URL", ""),
}


def _build_llm_from_config(cfg: dict[str, str] | None = None):
    """Create an LLM provider from explicit config dict."""
    from querybridge.llm.openai_provider import OpenAIProvider

    c = cfg or _llm_config
    provider = c.get("provider", "openai")
    api_key = c.get("api_key", "")
    model = c.get("model", "gpt-4o")
    base_url = c.get("base_url", "") or None

    if provider == "anthropic":
        from querybridge.llm.anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=api_key, model=model)
    elif provider == "litellm":
        from querybridge.llm.litellm_provider import LiteLLMProvider
        return LiteLLMProvider(model=model, api_key=api_key)
    else:
        extra: dict[str, Any] = {"api_key": api_key}
        # Support custom OpenAI-compatible gateways that use a
        # subscription header instead of the Authorization header.
        custom_header = os.getenv("QUERYBRIDGE_CUSTOM_AUTH_HEADER")
        if custom_header:
            extra["default_headers"] = {custom_header: api_key}
            extra["api_key"] = "dummy"
        return OpenAIProvider(model=model, base_url=base_url, **extra)


def _build_llm():
    """Create the shared LLM provider from current config."""
    return _build_llm_from_config(_llm_config)


def _build_connector(db_type: str, dsn: str):
    """Create a connector for the given type and DSN."""
    if db_type == "sqlite":
        from querybridge.connectors.sqlite import SQLiteConnector
        return SQLiteConnector(dsn.replace("sqlite:///", ""))
    elif db_type == "postgresql":
        from querybridge.connectors.postgresql import PostgreSQLConnector
        return PostgreSQLConnector(dsn)
    else:
        from querybridge.connectors.generic_sqlalchemy import GenericSQLAlchemyConnector
        return GenericSQLAlchemyConnector(dsn)


def _build_engine(connector: Any, llm: Any):
    from querybridge.core.config import EngineConfig
    from querybridge.core.engine import QueryBridgeEngine
    return QueryBridgeEngine(connector=connector, llm=llm, config=EngineConfig())


def _detect_db_type(dsn: str) -> str:
    """Infer database type from DSN string."""
    dsn_lower = dsn.lower()
    if "sqlite" in dsn_lower:
        return "sqlite"
    if "postgres" in dsn_lower:
        return "postgresql"
    if "mysql" in dsn_lower:
        return "mysql"
    if "mssql" in dsn_lower or "sqlserver" in dsn_lower:
        return "mssql"
    if "snowflake" in dsn_lower:
        return "snowflake"
    if "bigquery" in dsn_lower:
        return "bigquery"
    return "generic"


async def _register_datasource(
    name: str,
    db_type: str,
    dsn: str,
    active: bool = True,
    is_default: bool = False,
    ds_id: str | None = None,
) -> dict[str, Any]:
    """Register a datasource and build its engine."""
    global _llm
    if _llm is None:
        _llm = _build_llm()
    connector = _build_connector(db_type, dsn)
    engine = _build_engine(connector, _llm)
    ds_id = ds_id or str(uuid.uuid4())[:8]
    _datasources[ds_id] = {
        "id": ds_id,
        "name": name,
        "type": db_type,
        "_dsn": dsn,
        "dsn_display": _mask_dsn(dsn),
        "active": active,
        "default": is_default,
        "engine": engine,
    }
    logger.info(f"Datasource registered: {name} ({db_type}) id={ds_id}")
    return _datasources[ds_id]


def _mask_dsn(dsn: str) -> str:
    """Mask password in DSN for display."""
    import re
    return re.sub(r"://([^:]+):([^@]+)@", r"://\1:****@", dsn)


def _get_active_engines() -> list[tuple[str, str, Any]]:
    """Return list of (id, name, engine) for active datasources."""
    return [
        (ds["id"], ds["name"], ds["engine"])
        for ds in _datasources.values()
        if ds["active"] and ds.get("engine")
    ]


def _ds_to_json(ds: dict[str, Any]) -> dict[str, Any]:
    """Serialize datasource for API response (no engine/dsn)."""
    return {k: v for k, v in ds.items() if k not in ("engine", "_dsn")}


# ── App factory ────────────────────────────────────────────────────────

def create_app() -> Any:
    try:
        from fastapi import FastAPI, HTTPException
        from fastapi.middleware.cors import CORSMiddleware
        from pydantic import BaseModel
    except ImportError as err:
        raise ImportError(
            "FastAPI is required for API mode. "
            "Install with: pip install querybridge[server]"
        ) from err

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Auto-register default datasource from env, falling back to demo DB
        dsn = os.getenv("QUERYBRIDGE_DSN")
        api_key = os.getenv("QUERYBRIDGE_API_KEY")
        if dsn and api_key:
            db_type = _detect_db_type(dsn)
            await _register_datasource(
                name=os.getenv("QUERYBRIDGE_DEFAULT_NAME", "Default Database"),
                db_type=db_type,
                dsn=dsn,
                active=True,
                is_default=True,
                ds_id="default",
            )
        else:
            # Fall back to the bundled Chinook demo database
            demo_path = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                os.pardir, os.pardir, os.pardir, "demo", "chinook.db",
            )
            # Also check Docker path /app/demo/chinook.db
            if not os.path.isfile(demo_path):
                demo_path = "/app/demo/chinook.db"
            if os.path.isfile(demo_path):
                demo_dsn = f"sqlite:///{os.path.abspath(demo_path)}"
                logger.info("No QUERYBRIDGE_DSN set — loading demo Chinook DB")
                await _register_datasource(
                    name="Chinook Music Store (Demo)",
                    db_type="sqlite",
                    dsn=demo_dsn,
                    active=True,
                    is_default=True,
                    ds_id="default",
                )
            else:
                logger.warning(
                    "QUERYBRIDGE_DSN not set and demo/chinook.db not found"
                )
        yield
        for ds in _datasources.values():
            eng = ds.get("engine")
            if eng:
                try:
                    await eng.close()
                except Exception:
                    pass
        _datasources.clear()

    app = FastAPI(
        title="QueryBridge",
        description="Natural Language to SQL API",
        version="0.2.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request / Response models ────────────────────────────────────

    class ChatRequest(BaseModel):
        message: str
        chat_id: str | None = None
        history: list[dict[str, Any]] | None = []
        datasource_ids: list[str] | None = None  # None = all active

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
        datasource_id: str | None = None
        datasource_name: str | None = None

    class MultiChatResponse(BaseModel):
        results: list[ChatResponse]
        total_time_ms: int

    class DatasourceAdd(BaseModel):
        name: str
        type: str  # postgresql, sqlite, mysql, mssql, snowflake, bigquery
        dsn: str

    class DatasourceOut(BaseModel):
        id: str
        name: str
        type: str
        dsn_display: str
        active: bool
        default: bool

    class DatasourceTest(BaseModel):
        type: str
        dsn: str

    # ── Datasource management endpoints ──────────────────────────────

    @app.get("/api/datasources", response_model=list[DatasourceOut])
    async def list_datasources():
        return [_ds_to_json(ds) for ds in _datasources.values()]

    @app.post("/api/datasources", response_model=DatasourceOut, status_code=201)
    async def add_datasource(body: DatasourceAdd):
        if len(_datasources) >= 10:
            raise HTTPException(400, "Maximum 10 datasources allowed")
        ds = await _register_datasource(
            name=body.name, db_type=body.type, dsn=body.dsn,
        )
        return _ds_to_json(ds)

    @app.delete("/api/datasources/{ds_id}")
    async def remove_datasource(ds_id: str):
        ds = _datasources.get(ds_id)
        if not ds:
            raise HTTPException(404, "Datasource not found")
        if ds.get("default"):
            raise HTTPException(400, "Cannot remove the default datasource")
        eng = ds.get("engine")
        if eng:
            try:
                await eng.close()
            except Exception:
                pass
        del _datasources[ds_id]
        return {"ok": True}

    @app.patch("/api/datasources/{ds_id}")
    async def toggle_datasource(ds_id: str):
        ds = _datasources.get(ds_id)
        if not ds:
            raise HTTPException(404, "Datasource not found")
        ds["active"] = not ds["active"]
        return _ds_to_json(ds)

    @app.post("/api/datasources/test")
    async def test_datasource(body: DatasourceTest):
        """Test connectivity to a datasource without saving it."""
        try:
            connector = _build_connector(body.type, body.dsn)
            tables = await connector.get_tables()
            await connector.close()
            return {"ok": True, "tables": len(tables)}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ── Chat endpoint (supports multi-DB) ────────────────────────────

    @app.post("/api/chat")
    async def chat(body: ChatRequest):
        # Determine which engines to query
        if body.datasource_ids:
            targets = []
            for did in body.datasource_ids:
                ds = _datasources.get(did)
                if ds and ds["active"] and ds.get("engine"):
                    targets.append((ds["id"], ds["name"], ds["engine"]))
            if not targets:
                raise HTTPException(400, "No valid active datasources selected")
        else:
            targets = _get_active_engines()

        if not targets:
            raise HTTPException(400, "No active datasources available")

        # Single datasource — return flat response
        if len(targets) == 1:
            ds_id, ds_name, engine = targets[0]
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
                datasource_id=ds_id,
                datasource_name=ds_name,
            )

        # Multiple datasources — query each, return combined
        import asyncio
        start = time.monotonic()
        results = []

        async def _query_one(ds_id: str, ds_name: str, eng: Any):
            resp = await eng.query(
                question=body.message,
                chat_id=body.chat_id,
                history=body.history,
            )
            return ChatResponse(
                answer=resp.answer,
                chat_id=resp.chat_id,
                queries_executed=len(resp.query_log),
                query_log=resp.query_log,
                total_time_ms=resp.total_time_ms,
                last_sql=resp.last_sql,
                thinking_steps=resp.thinking_steps,
                confidence=resp.confidence,
                iterations_used=resp.iterations_used,
                datasource_id=ds_id,
                datasource_name=ds_name,
            )

        tasks = [_query_one(did, dn, eng) for did, dn, eng in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        chat_results = []
        for i, r in enumerate(results):
            if isinstance(r, Exception):
                ds_id, ds_name, _ = targets[i]
                chat_results.append(ChatResponse(
                    answer=f"Error from {ds_name}: {r}",
                    chat_id=body.chat_id or "",
                    queries_executed=0,
                    query_log=[],
                    total_time_ms=0,
                    datasource_id=ds_id,
                    datasource_name=ds_name,
                ))
            else:
                chat_results.append(r)

        total_ms = int((time.monotonic() - start) * 1000)
        return MultiChatResponse(results=chat_results, total_time_ms=total_ms)

    # ── LLM configuration endpoints ────────────────────────────────────

    class LLMConfig(BaseModel):
        provider: str = "openai"  # openai, anthropic, litellm
        api_key: str = ""
        model: str = "gpt-4o"
        base_url: str = ""

    class LLMConfigOut(BaseModel):
        provider: str
        model: str
        base_url: str
        has_key: bool  # never expose the actual key

    @app.get("/api/llm", response_model=LLMConfigOut)
    async def get_llm_config():
        return LLMConfigOut(
            provider=_llm_config["provider"],
            model=_llm_config["model"],
            base_url=_llm_config["base_url"],
            has_key=bool(_llm_config["api_key"]),
        )

    @app.put("/api/llm", response_model=LLMConfigOut)
    async def update_llm_config(body: LLMConfig):
        """Update the LLM provider and rebuild all engines."""
        global _llm
        _llm_config["provider"] = body.provider
        _llm_config["model"] = body.model
        _llm_config["base_url"] = body.base_url
        if body.api_key:  # only update key if provided (non-empty)
            _llm_config["api_key"] = body.api_key
        # Rebuild the shared LLM
        _llm = _build_llm_from_config(_llm_config)
        # Rebuild every datasource engine with the new LLM
        for ds in _datasources.values():
            old_eng = ds.get("engine")
            if old_eng:
                try:
                    await old_eng.close()
                except Exception:
                    pass
            connector = _build_connector(ds["type"], ds.get("_dsn", ""))
            ds["engine"] = _build_engine(connector, _llm)
        logger.info(f"LLM updated: {body.provider}/{body.model}")
        return LLMConfigOut(
            provider=_llm_config["provider"],
            model=_llm_config["model"],
            base_url=_llm_config["base_url"],
            has_key=bool(_llm_config["api_key"]),
        )

    @app.get("/health")
    async def health():
        active = _get_active_engines()
        return {
            "status": "ok",
            "engine_ready": len(active) > 0,
            "datasources": len(_datasources),
            "active_datasources": len(active),
            "llm_provider": _llm_config["provider"],
            "llm_model": _llm_config["model"],
            "llm_configured": bool(_llm_config["api_key"]),
        }

    return app


# Module-level app instance for `uvicorn querybridge.server.api:app`
app = create_app()
