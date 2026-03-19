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
    elif db_type == "snowflake":
        from querybridge.connectors.snowflake import SnowflakeConnector
        return SnowflakeConnector(dsn)
    else:
        from querybridge.connectors.generic_sqlalchemy import GenericSQLAlchemyConnector
        return GenericSQLAlchemyConnector(dsn)


def _build_engine(connector: Any, llm: Any, db_type: str = "", dsn: str = "", ds_id: str = "default"):
    from querybridge.core.config import EngineConfig
    from querybridge.core.engine import QueryBridgeEngine

    plugin = _detect_plugin(db_type, dsn)
    return QueryBridgeEngine(connector=connector, llm=llm, config=EngineConfig(), plugin=plugin, datasource_id=ds_id)


def _detect_plugin(db_type: str, dsn: str) -> Any:
    """Auto-detect the best domain plugin based on database type and DSN."""
    dsn_lower = (dsn or "").lower()
    # Manufacturing plugin for Silicon Trace or Snowflake MFG databases
    if (
        "silicon" in dsn_lower
        or "mfg" in dsn_lower
        or "datacenter" in dsn_lower
        or "analysis_facts" in dsn_lower
        or db_type == "snowflake"
    ):
        from querybridge.plugins.builtin.manufacturing import ManufacturingPlugin
        return ManufacturingPlugin()
    return None  # GenericPlugin used as default by engine


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
    ds_id = ds_id or str(uuid.uuid4())[:8]
    connector = _build_connector(db_type, dsn)
    engine = _build_engine(connector, _llm, db_type=db_type, dsn=dsn, ds_id=ds_id)

    # Attach RAG sync for PostgreSQL datasources that have rag_query_memory
    if db_type == "postgresql":
        try:
            from querybridge.memory.rag_sync import RAGSync
            rag = RAGSync(pg_dsn=dsn)
            engine.rag_sync = rag
            engine._agent.rag_sync = rag
            logger.info("RAGSync enabled for datasource %s", name)
        except Exception as e:
            logger.debug("RAGSync not available for %s: %s", name, e)

    # Eagerly initialize schema cache (fast Tier 1 index, ~2s)
    try:
        mode = await engine.schema_cache.initialize()
        logger.info(f"Schema cache initialized for {name}: mode={mode}")
    except Exception as e:
        logger.warning(f"Schema cache init failed for {name}: {e}")

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


# ── Meta-question detection ────────────────────────────────────────────

import re as _re

_META_PATTERNS = [
    _re.compile(r"\bhow\s+many\s+(?:database|datasource|data\s*source|db)s?\b", _re.IGNORECASE),
    _re.compile(r"\bwhich\s+(?:database|datasource|data\s*source|db)s?\s+(?:are|is)\s+(?:connected|available|active|running)\b", _re.IGNORECASE),
    _re.compile(r"\blist\s+(?:all\s+)?(?:database|datasource|data\s*source|db)s?\b", _re.IGNORECASE),
    _re.compile(r"\bwhat\s+(?:database|datasource|data\s*source|db)s?\s+(?:are|do)\b", _re.IGNORECASE),
    _re.compile(r"\b(?:database|datasource|data\s*source|db)s?\s+(?:connected|available|active)\b", _re.IGNORECASE),
    _re.compile(r"\bconnected\s+(?:database|datasource|data\s*source|db)s?\b", _re.IGNORECASE),
]


def _check_meta_question(question: str) -> str | None:
    """Check if the question is about the system itself (not SQL-queryable).

    Returns a direct answer string if it's a meta-question, or None to proceed normally.
    """
    q = question.strip()
    is_meta = any(p.search(q) for p in _META_PATTERNS)
    if not is_meta:
        return None

    active = [(ds["id"], ds["name"], ds["type"], ds["active"]) for ds in _datasources.values()]
    active_count = sum(1 for _, _, _, a in active if a)
    total_count = len(active)

    lines = [f"**{active_count} database{'s' if active_count != 1 else ''} currently connected** ({total_count} total):\n"]
    for ds_id, name, db_type, is_active in active:
        status = "✅ Active" if is_active else "⏸️ Inactive"
        lines.append(f"| {name} | {db_type} | {status} |")

    header = "| Database | Type | Status |\n|---|---|---|"
    return lines[0] + "\n" + header + "\n" + "\n".join(lines[1:])


def _recall_routing_context(question: str) -> str:
    """Recall routing experience from any active engine's exploration memory."""
    for ds in _datasources.values():
        engine = ds.get("engine")
        if engine and hasattr(engine, "exploration_memory") and engine.exploration_memory:
            try:
                notes = engine.exploration_memory.recall_routing(question, limit=5)
                if notes:
                    return engine.exploration_memory.format_routing_context(notes)
            except Exception:
                pass
    return ""


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
        # Auto-register default datasource from env
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

        # Always register the bundled Chinook demo DB when the file exists.
        # If no QUERYBRIDGE_DSN was set it becomes the default; otherwise it
        # is added as an extra datasource users can query from the playground.
        demo_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir, os.pardir, os.pardir, "demo", "chinook.db",
        )
        if not os.path.isfile(demo_path):
            demo_path = "/app/demo/chinook.db"
        if os.path.isfile(demo_path):
            demo_dsn = f"sqlite:///{os.path.abspath(demo_path)}"
            is_default = "default" not in _datasources
            logger.info("Registering Chinook demo DB (default=%s)", is_default)
            await _register_datasource(
                name="Chinook Music Store (Demo)",
                db_type="sqlite",
                dsn=demo_dsn,
                active=True,
                is_default=is_default,
                ds_id="demo",
            )
        elif not _datasources:
            logger.warning(
                "QUERYBRIDGE_DSN not set and demo/chinook.db not found"
            )

        # Auto-register Snowflake if env vars are present
        sf_account = os.getenv("SNOWFLAKE_ACCOUNT")
        sf_user = os.getenv("SNOWFLAKE_USER")
        if sf_account and sf_user:
            sf_role = os.getenv("SNOWFLAKE_ROLE", "PUBLIC")
            sf_wh = os.getenv("SNOWFLAKE_WAREHOUSE", "")
            sf_db = os.getenv("SNOWFLAKE_DATABASE", "")
            sf_schema = os.getenv("SNOWFLAKE_SCHEMA", "")
            sf_key = os.getenv("SNOWFLAKE_PRIVATE_KEY_PATH", "")
            sf_dsn = (
                f"snowflake://{sf_user}@{sf_account}/{sf_db}/{sf_schema}"
                f"?warehouse={sf_wh}&role={sf_role}"
            )
            if sf_key:
                sf_dsn += f"&private_key_path={sf_key}"
            try:
                await _register_datasource(
                    name=f"{sf_db} ({sf_schema})",
                    db_type="snowflake",
                    dsn=sf_dsn,
                    active=True,
                    is_default=False,
                    ds_id="snowflake",
                )
            except Exception as exc:
                logger.warning("Snowflake auto-register failed: %s", exc)

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
        routed_to: list[str] | None = None  # DB names the router selected

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
        from querybridge.server.router import invalidate_fingerprint
        invalidate_fingerprint(ds_id)
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
        from querybridge.server.router import route_question, invalidate_fingerprint

        # Intercept system meta-questions
        meta_answer = _check_meta_question(body.message)
        if meta_answer:
            return ChatResponse(
                answer=meta_answer,
                chat_id=body.chat_id or "",
                queries_executed=0,
                query_log=[],
                total_time_ms=0,
                confidence=1.0,
            )

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

        # Smart routing: use schema fingerprints to pick the best DB(s)
        routed_names: list[str] | None = None
        if len(targets) > 1 and _llm:
            routing_ctx = _recall_routing_context(body.message)
            targets = await route_question(body.message, targets, _llm, routing_context=routing_ctx)
            routed_names = [name for _, name, _ in targets]

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
                routed_to=routed_names,
            )

        # Multiple datasources — query each in parallel, then synthesize
        import asyncio
        start = time.monotonic()

        async def _query_one(ds_id: str, ds_name: str, eng: Any):
            resp = await eng.query(
                question=body.message,
                chat_id=body.chat_id,
                history=body.history,
            )
            return {
                "answer": resp.answer,
                "chat_id": resp.chat_id,
                "query_log": resp.query_log,
                "total_time_ms": resp.total_time_ms,
                "last_sql": resp.last_sql,
                "thinking_steps": resp.thinking_steps,
                "confidence": resp.confidence,
                "iterations_used": resp.iterations_used,
                "datasource_id": ds_id,
                "datasource_name": ds_name,
            }

        tasks = [_query_one(did, dn, eng) for did, dn, eng in targets]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

        db_results = []
        for i, r in enumerate(raw_results):
            if isinstance(r, Exception):
                ds_id, ds_name, _ = targets[i]
                db_results.append({
                    "answer": f"Error: {r}",
                    "chat_id": body.chat_id or "",
                    "query_log": [],
                    "total_time_ms": 0,
                    "last_sql": None,
                    "thinking_steps": [],
                    "confidence": 0.0,
                    "iterations_used": 0,
                    "datasource_id": ds_id,
                    "datasource_name": ds_name,
                })
            else:
                db_results.append(r)

        total_ms = int((time.monotonic() - start) * 1000)

        # Synthesize unified answer via LLM
        synthesis_parts = []
        for r in db_results:
            synthesis_parts.append(
                f"### {r['datasource_name']}\n"
                f"Answer: {r['answer']}\n"
                f"SQL used: {r.get('last_sql') or '(none)'}\n"
                f"Confidence: {r['confidence']:.0%}\n"
            )

        synthesis_prompt = (
            "You are a data analyst assistant. The user asked a question that was "
            "routed to multiple databases. Below are the individual results from each "
            "database. Synthesize these into ONE clear, unified answer.\n\n"
            "Rules:\n"
            "- Combine information from all databases into a single coherent response\n"
            "- Note which database each piece of information came from using **bold** labels\n"
            "- If databases have overlapping data, reconcile or note differences\n"
            "- If a database returned an error, mention it briefly\n"
            "- Use markdown tables where appropriate\n"
            "- Keep the answer concise and well-organized\n\n"
            f"User question: {body.message}\n\n"
            "Database results:\n" + "\n".join(synthesis_parts)
        )

        try:
            synth_resp = await _llm.chat(
                messages=[{"role": "user", "content": synthesis_prompt}],
                temperature=0.0,
                max_tokens=4096,
            )
            unified_answer = synth_resp.content or "Could not synthesize results."
        except Exception as e:
            logger.warning("Synthesis LLM call failed: %s", e)
            parts = []
            for r in db_results:
                parts.append(f"**{r['datasource_name']}**\n\n{r['answer']}")
            unified_answer = "\n\n---\n\n".join(parts)

        best = max(db_results, key=lambda r: r["confidence"])
        all_query_log = []
        all_thinking = []
        for r in db_results:
            all_query_log.extend(r["query_log"])
            all_thinking.extend(r.get("thinking_steps") or [])

        return ChatResponse(
            answer=unified_answer,
            chat_id=best["chat_id"],
            queries_executed=len(all_query_log),
            query_log=all_query_log,
            total_time_ms=total_ms,
            last_sql=best.get("last_sql"),
            thinking_steps=all_thinking,
            confidence=sum(r["confidence"] for r in db_results) / len(db_results),
            iterations_used=sum(r["iterations_used"] for r in db_results),
            datasource_name=", ".join(r["datasource_name"] for r in db_results),
            routed_to=routed_names,
        )

    # ── SSE streaming chat endpoint ─────────────────────────────────

    @app.post("/api/chat/stream")
    async def chat_stream(body: ChatRequest):
        """Stream progress events via Server-Sent Events (SSE).

        Supports multi-DB: queries all routed databases sequentially,
        then synthesizes a unified answer via LLM.

        Yields events as `data: {json}\\n\\n` lines. Event types:
          - status: {step, detail}
          - thinking: {iteration, phase, reasoning}
          - tool_call: {iteration, tool, args}
          - tool_result: {iteration, tool, summary}
          - routing: {routed_to}
          - complete: {unified answer}
        """
        from starlette.responses import StreamingResponse
        from querybridge.server.router import route_question

        # Intercept system meta-questions
        meta_answer = _check_meta_question(body.message)
        if meta_answer:
            async def _meta_gen():
                import json as _json
                yield f"data: {_json.dumps({'type': 'complete', 'answer': meta_answer, 'chat_id': body.chat_id or '', 'queries_executed': 0, 'query_log': [], 'total_time_ms': 0, 'thinking_steps': [], 'confidence': 1.0, 'iterations_used': 0}, default=str)}\n\n"
            return StreamingResponse(_meta_gen(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

        # Determine targets (same logic as /api/chat)
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

        async def event_generator():
            import json as _json

            def sse(data: dict) -> str:
                return f"data: {_json.dumps(data, default=str)}\n\n"

            # Smart routing
            routed_names: list[str] | None = None
            active_targets = targets
            if len(active_targets) > 1 and _llm:
                routing_ctx = _recall_routing_context(body.message)
                active_targets = await route_question(body.message, active_targets, _llm, routing_context=routing_ctx)
                routed_names = [name for _, name, _ in active_targets]
                yield sse({"type": "routing", "routed_to": routed_names})

            # ── Query each routed DB (stream progress for each) ────
            db_results: list[dict] = []  # collected per-DB responses
            all_thinking: list[dict] = []
            all_query_log: list[dict] = []
            total_start = time.monotonic()

            for idx, (ds_id, ds_name, engine) in enumerate(active_targets):
                yield sse({"type": "status", "step": "start",
                           "detail": f"Querying {ds_name}... ({idx + 1}/{len(active_targets)})"})

                async for event in engine.query_stream(
                    question=body.message,
                    chat_id=body.chat_id,
                    history=body.history,
                ):
                    if event.get("type") == "complete":
                        resp = event["response"]
                        db_results.append({
                            "answer": resp.answer,
                            "chat_id": resp.chat_id,
                            "query_log": resp.query_log,
                            "total_time_ms": resp.total_time_ms,
                            "last_sql": resp.last_sql,
                            "thinking_steps": resp.thinking_steps,
                            "confidence": resp.confidence,
                            "iterations_used": resp.iterations_used,
                            "datasource_id": ds_id,
                            "datasource_name": ds_name,
                        })
                        all_query_log.extend(resp.query_log)
                        all_thinking.extend(resp.thinking_steps or [])
                    else:
                        # Tag non-complete events with datasource for multi-DB clarity
                        if len(active_targets) > 1:
                            event["datasource_name"] = ds_name
                        yield sse(event)

            total_ms = int((time.monotonic() - total_start) * 1000)

            # ── Single DB: return directly ─────────────────────────
            if len(db_results) == 1:
                r = db_results[0]
                yield sse({
                    "type": "complete",
                    "answer": r["answer"],
                    "chat_id": r["chat_id"],
                    "queries_executed": len(r["query_log"]),
                    "query_log": r["query_log"],
                    "total_time_ms": r["total_time_ms"],
                    "last_sql": r["last_sql"],
                    "thinking_steps": r["thinking_steps"],
                    "confidence": r["confidence"],
                    "iterations_used": r["iterations_used"],
                    "datasource_id": r["datasource_id"],
                    "datasource_name": r["datasource_name"],
                    "routed_to": routed_names,
                })
                return

            # ── Multiple DBs: synthesize unified answer ────────────
            if not db_results:
                yield sse({"type": "complete", "answer": "No results from any database.",
                           "chat_id": body.chat_id or "", "queries_executed": 0,
                           "query_log": [], "total_time_ms": total_ms})
                return

            yield sse({"type": "status", "step": "synthesis",
                       "detail": "Compiling results from all databases..."})

            # Build synthesis prompt from collected answers
            synthesis_parts = []
            for r in db_results:
                synthesis_parts.append(
                    f"### {r['datasource_name']}\n"
                    f"Answer: {r['answer']}\n"
                    f"SQL used: {r.get('last_sql') or '(none)'}\n"
                    f"Confidence: {r['confidence']:.0%}\n"
                )

            synthesis_prompt = (
                "You are a data analyst assistant. The user asked a question that was "
                "routed to multiple databases. Below are the individual results from each "
                "database. Synthesize these into ONE clear, unified answer.\n\n"
                "Rules:\n"
                "- Combine information from all databases into a single coherent response\n"
                "- Note which database each piece of information came from using **bold** labels\n"
                "- If databases have overlapping data, reconcile or note differences\n"
                "- If a database returned an error, mention it briefly\n"
                "- Use markdown tables where appropriate\n"
                "- Keep the answer concise and well-organized\n\n"
                f"User question: {body.message}\n\n"
                "Database results:\n" + "\n".join(synthesis_parts)
            )

            try:
                synth_resp = await _llm.chat(
                    messages=[{"role": "user", "content": synthesis_prompt}],
                    temperature=0.0,
                    max_tokens=4096,
                )
                unified_answer = synth_resp.content or "Could not synthesize results."
            except Exception as e:
                logger.warning("Synthesis LLM call failed: %s", e)
                # Fallback: concatenate answers with headers
                parts = []
                for r in db_results:
                    parts.append(f"**{r['datasource_name']}**\n\n{r['answer']}")
                unified_answer = "\n\n---\n\n".join(parts)

            # Pick the best chat_id and last_sql
            best = max(db_results, key=lambda r: r["confidence"])
            yield sse({
                "type": "complete",
                "answer": unified_answer,
                "chat_id": best["chat_id"],
                "queries_executed": len(all_query_log),
                "query_log": all_query_log,
                "total_time_ms": total_ms,
                "last_sql": best.get("last_sql"),
                "thinking_steps": all_thinking,
                "confidence": sum(r["confidence"] for r in db_results) / len(db_results),
                "iterations_used": sum(r["iterations_used"] for r in db_results),
                "datasource_id": None,
                "datasource_name": ", ".join(r["datasource_name"] for r in db_results),
                "routed_to": routed_names,
            })

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

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
            ds["engine"] = _build_engine(connector, _llm, db_type=ds["type"], dsn=ds.get("_dsn", ""), ds_id=ds["id"])
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

    @app.get("/api/query-memory/{ds_id}")
    async def query_memory_stats(ds_id: str):
        """Get query memory statistics for a datasource."""
        ds = _datasources.get(ds_id)
        if not ds or not ds.get("engine"):
            raise HTTPException(404, "Datasource not found")
        pm = ds["engine"].persistent_memory
        return {"datasource_id": ds_id, "datasource_name": ds["name"], **pm.get_stats()}

    @app.get("/api/query-memory")
    async def all_query_memory_stats():
        """Get query memory statistics for all active datasources."""
        results = {}
        for ds_id, ds in _datasources.items():
            if ds.get("engine"):
                pm = ds["engine"].persistent_memory
                results[ds_id] = {"name": ds["name"], **pm.get_stats()}
        return results

    return app


# Module-level app instance for `uvicorn querybridge.server.api:app`
app = create_app()
