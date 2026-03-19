"""Schema-aware datasource router.

Uses cached schema fingerprints to let the LLM decide which database(s)
are relevant for a user question — before running the full agentic loop.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("querybridge.server.router")

# Module-level cache: ds_id → {"name": ..., "tables": [...], "fingerprint": "..."}
_schema_fingerprints: dict[str, dict[str, Any]] = {}

ROUTER_SYSTEM_PROMPT = """\
You are a database router. Given a user question and a list of available databases \
with their schemas, return a JSON array of database IDs that are relevant to the question.

Rules:
- Return ONLY the JSON array, e.g. ["db1"] or ["db1","db2"]. No explanation.
- Pick the database(s) whose tables/columns best match the question's intent.
- If a question could apply to multiple databases, include all relevant ones.
- If no database is clearly relevant, return all IDs.
- Prefer fewer databases when the match is unambiguous."""


async def build_fingerprint(ds_id: str, ds_name: str, engine: Any) -> str:
    """Build a compact schema fingerprint for routing decisions.

    Returns a human-readable string like:
       Silicon Trace (id=default): tables: assets(id, asset_name, tier, customer_name, ...),
       failures(id, asset_id, failure_mode, root_cause, ...), ...
    """
    try:
        # Use schema index (Tier 1) if available — avoids full discovery
        index = engine.schema_cache.schema_index
        if index and index.tables:
            parts = []
            for table_name in sorted(index.tables.keys()):
                cols = index.tables[table_name][:12]
                if len(index.tables[table_name]) > 12:
                    cols = cols + [f"...+{len(index.tables[table_name]) - 12} more"]
                parts.append(f"{table_name}({', '.join(cols)})")
            fingerprint = f"{ds_name} (id={ds_id}): {'; '.join(parts)}"
            _schema_fingerprints[ds_id] = {
                "name": ds_name,
                "tables": list(index.tables.keys()),
                "fingerprint": fingerprint,
            }
            logger.info(
                "Schema fingerprint built from index for %s: %d tables",
                ds_name, index.table_count,
            )
            return fingerprint

        # Fallback to full schema
        schema = await engine.schema_cache.get_schema()
        parts = []
        for table in schema.tables:
            cols = schema.columns.get(table.name, [])
            col_names = [c.name for c in cols[:12]]  # Cap at 12 cols per table
            if len(cols) > 12:
                col_names.append(f"...+{len(cols) - 12} more")
            parts.append(f"{table.name}({', '.join(col_names)})")
        fingerprint = f"{ds_name} (id={ds_id}): {'; '.join(parts)}"
        _schema_fingerprints[ds_id] = {
            "name": ds_name,
            "tables": [t.name for t in schema.tables],
            "fingerprint": fingerprint,
        }
        logger.info("Schema fingerprint built for %s: %d tables", ds_name, len(schema.tables))
        return fingerprint
    except Exception as e:
        logger.warning("Failed to build fingerprint for %s: %s", ds_name, e)
        # Fall back to just the name
        fp = f"{ds_name} (id={ds_id}): (schema unavailable)"
        _schema_fingerprints[ds_id] = {"name": ds_name, "tables": [], "fingerprint": fp}
        return fp


async def route_question(
    question: str,
    active_datasources: list[tuple[str, str, Any]],
    llm: Any,
    routing_context: str = "",
) -> list[tuple[str, str, Any]]:
    """Pick the best datasource(s) for a question using schema fingerprints.

    Args:
        question: The user's natural language question.
        active_datasources: List of (ds_id, ds_name, engine) tuples for active datasources.
        llm: The shared LLM provider for the routing call.
        routing_context: Optional past routing experience notes from ExplorationMemory.

    Returns:
        A filtered list of (ds_id, ds_name, engine) tuples to query.
    """
    if len(active_datasources) <= 1:
        return active_datasources

    # Build fingerprints for any datasource that doesn't have one yet
    for ds_id, ds_name, engine in active_datasources:
        if ds_id not in _schema_fingerprints:
            await build_fingerprint(ds_id, ds_name, engine)

    # Build the routing prompt
    db_descriptions = "\n".join(
        _schema_fingerprints[ds_id]["fingerprint"]
        for ds_id, _, _ in active_datasources
        if ds_id in _schema_fingerprints
    )

    user_prompt = f"Databases:\n{db_descriptions}\n\nQuestion: {question}"
    if routing_context:
        user_prompt += f"\n\n{routing_context}"

    try:
        # Quick LLM call — just routing, no SQL
        messages = [
            {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]
        resp = await llm.chat(messages=messages, max_tokens=100, temperature=0.0)
        text = (resp.content or "").strip()
        # Handle markdown code blocks
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        selected_ids = json.loads(text)

        if not isinstance(selected_ids, list) or not selected_ids:
            logger.warning("Router returned invalid response: %s; falling back to all", text)
            return active_datasources

        # Filter to only the selected datasources
        id_set = set(selected_ids)
        routed = [t for t in active_datasources if t[0] in id_set]

        if not routed:
            logger.warning("Router selected unknown IDs %s; falling back to all", selected_ids)
            return active_datasources

        logger.info(
            "Router selected %s for question: %.60s",
            [r[1] for r in routed],
            question,
        )
        return routed

    except Exception as e:
        logger.warning("Router LLM call failed: %s; falling back to all", e)
        return active_datasources


def invalidate_fingerprint(ds_id: str) -> None:
    """Remove a cached fingerprint (e.g. when a datasource is removed)."""
    _schema_fingerprints.pop(ds_id, None)
