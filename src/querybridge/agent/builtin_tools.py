"""Built-in tool handlers — wire tool calls to the DatabaseConnector."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector
    from querybridge.safety.guard import SQLGuard

logger = logging.getLogger("querybridge.agent.builtin_tools")

# Maximum result size in characters before truncation
MAX_RESULT_CHARS = 50_000


def _truncate_result(result: dict[str, Any]) -> dict[str, Any]:
    """Truncate large results to avoid token overflow."""
    result_str = json.dumps(result, default=str)
    if len(result_str) <= MAX_RESULT_CHARS:
        return result
    keep_keys = {"columns", "error", "table", "column", "path", "_validation_notes"}
    truncated = {k: v for k, v in result.items() if k in keep_keys}
    truncated["rows"] = result.get("rows", [])[:50]
    truncated["row_count"] = result.get("row_count", 0)
    truncated["truncated"] = True
    truncated["note"] = "Results truncated for token limit"
    return truncated


async def handle_execute_sql(
    connector: DatabaseConnector,
    guard: SQLGuard,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Execute a SQL query through the guard and connector."""
    sql = args.get("sql", "")
    reason = args.get("reason", "")

    is_safe, guard_reason = guard.validate(sql)
    if not is_safe:
        query_log.append({
            "iteration": iteration,
            "sql": sql,
            "reason": reason,
            "blocked": True,
            "block_reason": guard_reason,
        })
        logger.warning(f"SQLGuard blocked: {guard_reason} | SQL: {sql[:200]}")
        return {"error": f"Query blocked by SQLGuard: {guard_reason}"}

    try:
        result = await connector.execute(sql)
        query_log.append({
            "iteration": iteration,
            "sql": sql,
            "reason": reason,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_time_ms": result.execution_time_ms,
        })
        result_dict = {
            "columns": result.columns,
            "rows": result.rows,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "execution_time_ms": result.execution_time_ms,
        }
        return _truncate_result(result_dict)
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "sql": sql,
            "reason": reason,
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_explore_table(
    connector: DatabaseConnector,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Explore a table's structure."""
    table_name = args.get("table_name", "")
    try:
        result = await connector.explore_table(table_name)
        query_log.append({
            "iteration": iteration,
            "tool": "explore_table",
            "table": table_name,
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "explore_table",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_get_distinct_values(
    connector: DatabaseConnector,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Get distinct values of a column."""
    table_name = args.get("table_name", "")
    column = args.get("column", "")
    limit = min(args.get("limit", 25), 50)
    try:
        result = await connector.get_distinct_values(table_name, column, limit)
        query_log.append({
            "iteration": iteration,
            "tool": "get_distinct_values",
            "table": table_name,
            "column": column,
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "get_distinct_values",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_validate_filter_values(
    connector: DatabaseConnector,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Validate filter values exist in a column."""
    table_name = args.get("table_name", "")
    column = args.get("column", "")
    values = args.get("values", [])
    try:
        # Use connector's validate_filter_values if available, else fallback
        if hasattr(connector, "validate_filter_values"):
            result = await connector.validate_filter_values(table_name, column, values)
        else:
            # Fallback: check each value via distinct values
            distinct = await connector.get_distinct_values(table_name, column, 200)
            all_values = {str(v.get("value", "")).lower() for v in distinct.get("values", [])}
            checks = []
            for v in values:
                found = str(v).lower() in all_values
                checks.append({"value": v, "found": found})
            result = {"checks": checks}
        query_log.append({
            "iteration": iteration,
            "tool": "validate_filter_values",
            "table": table_name,
            "column": column,
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "validate_filter_values",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_column_profile(
    connector: DatabaseConnector,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Get statistical profile of a column."""
    table_name = args.get("table_name", "")
    column = args.get("column", "")
    where_clause = args.get("where_clause")
    try:
        result = await connector.column_profile(table_name, column, where_clause)
        query_log.append({
            "iteration": iteration,
            "tool": "column_profile",
            "table": table_name,
            "column": column,
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "column_profile",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_count_estimate(
    connector: DatabaseConnector,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Quick COUNT(*) with optional conditions."""
    table_name = args.get("table_name", "")
    conditions = args.get("conditions")

    # Build a safe COUNT query
    connector.get_dialect_name()
    # Use parameterized identifier — the guard will catch injection in conditions
    sql = f"SELECT COUNT(*) as count FROM {table_name}"
    if conditions:
        sql += f" WHERE {conditions}"

    try:
        result = await connector.execute(sql)
        count = result.rows[0].get("count", 0) if result.rows else 0
        query_log.append({
            "iteration": iteration,
            "tool": "count_estimate",
            "table": table_name,
            "count": count,
        })
        return {"table": table_name, "conditions": conditions, "count": count}
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "count_estimate",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_cross_validate(
    connector: DatabaseConnector,
    guard: SQLGuard,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Run two queries and compare results."""
    primary_sql = args.get("primary_sql", "")
    check_sql = args.get("check_sql", "")
    comparison_note = args.get("comparison_note", "")

    for sql_q in [primary_sql, check_sql]:
        is_safe, reason = guard.validate(sql_q)
        if not is_safe:
            query_log.append({
                "iteration": iteration,
                "tool": "cross_validate",
                "blocked": True,
                "block_reason": reason,
            })
            return {"error": f"Query blocked by SQLGuard: {reason}"}

    try:
        primary_result = await connector.execute(primary_sql)
        check_result = await connector.execute(check_sql)

        consistent = primary_result.row_count == check_result.row_count
        discrepancy_note = ""
        if not consistent:
            discrepancy_note = (
                f"Row count mismatch: primary={primary_result.row_count}, "
                f"check={check_result.row_count}"
            )

        result = {
            "primary_result": {
                "columns": primary_result.columns,
                "rows": primary_result.rows[:20],
                "row_count": primary_result.row_count,
            },
            "check_result": {
                "columns": check_result.columns,
                "rows": check_result.rows[:20],
                "row_count": check_result.row_count,
            },
            "consistent": consistent,
            "discrepancy_note": discrepancy_note,
            "comparison_note": comparison_note,
        }
        query_log.append({
            "iteration": iteration,
            "tool": "cross_validate",
            "consistent": consistent,
            "discrepancy_note": discrepancy_note,
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "cross_validate",
            "error": str(e),
        })
        return {"error": str(e)}


def search_schema_index(
    schema_index: dict[str, list[str]],
    column_types: dict[str, str],
    keywords: str,
) -> dict[str, Any]:
    """Search the schema index for tables/columns matching keywords.

    Pure in-memory fuzzy search — no DB calls. Returns matching tables
    with their columns and types.
    """
    terms = [t.lower() for t in keywords.split() if t]
    if not terms:
        return {"error": "No search keywords provided", "matches": []}

    scored: dict[str, float] = {}
    matched_cols: dict[str, list[str]] = {}

    for table, columns in schema_index.items():
        table_lower = table.lower()
        score = 0.0
        hits: list[str] = []

        for term in terms:
            # Table name match (high weight)
            if term in table_lower:
                score += 3.0
            # Exact table name match (bonus)
            if term == table_lower:
                score += 2.0

            # Column name matches
            for col in columns:
                col_lower = col.lower()
                if term in col_lower:
                    score += 1.5
                    hits.append(col)
                elif term == col_lower:
                    score += 2.0
                    hits.append(col)

        if score > 0:
            scored[table] = score
            matched_cols[table] = list(dict.fromkeys(hits))  # dedupe, keep order

    # Sort by score descending, take top 15
    ranked = sorted(scored.items(), key=lambda x: x[1], reverse=True)[:15]

    results = []
    for table, score in ranked:
        cols = schema_index[table]
        col_details = []
        for c in cols:
            dtype = column_types.get(f"{table}.{c}", "unknown")
            col_details.append({"name": c, "type": dtype})
        results.append({
            "table": table,
            "columns": col_details,
            "matched_columns": matched_cols.get(table, []),
            "relevance_score": round(score, 1),
        })

    return {
        "query": keywords,
        "match_count": len(results),
        "matches": results,
    }


async def handle_search_schema(
    schema_index: dict[str, list[str]],
    column_types: dict[str, str],
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Handle the search_schema tool call."""
    keywords = args.get("keywords", "")
    result = search_schema_index(schema_index, column_types, keywords)
    query_log.append({
        "iteration": iteration,
        "tool": "search_schema",
        "keywords": keywords,
        "match_count": result.get("match_count", 0),
    })
    return result


# ============================================================================
# Exploration Memory tool handlers
# ============================================================================

async def handle_recall_explorations(
    exploration_memory: Any,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Recall exploration notes from persistent memory."""
    topic = args.get("topic", "")
    note_types = args.get("note_types")
    try:
        notes = exploration_memory.recall(
            topic=topic,
            note_types=note_types,
            limit=8,
        )
        result = {
            "topic": topic,
            "notes_found": len(notes),
            "notes": [
                {
                    "id": n.id,
                    "type": n.note_type,
                    "subject": n.subject,
                    "content": n.content,
                    "confidence": n.confidence,
                    "times_used": n.times_used,
                }
                for n in notes
            ],
        }
        query_log.append({
            "iteration": iteration,
            "tool": "recall_explorations",
            "topic": topic,
            "notes_found": len(notes),
        })
        return result
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "recall_explorations",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_note_exploration(
    exploration_memory: Any,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
    source_question: str = "",
) -> dict[str, Any]:
    """Store an exploration note."""
    subject = args.get("subject", "")
    observation = args.get("observation", "")
    note_type = args.get("note_type", "table_profile")
    try:
        note_id = exploration_memory.note(
            note_type=note_type,
            subject=subject,
            content=observation,
            source_question=source_question,
        )
        query_log.append({
            "iteration": iteration,
            "tool": "note_exploration",
            "subject": subject,
            "note_type": note_type,
        })
        return {"stored": True, "note_id": note_id}
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "note_exploration",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_note_relationship(
    exploration_memory: Any,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Store a discovered relationship."""
    try:
        note_id = exploration_memory.note_relationship(
            from_table=args.get("from_table", ""),
            from_column=args.get("from_column", ""),
            to_table=args.get("to_table", ""),
            to_column=args.get("to_column", ""),
            notes=args.get("notes", ""),
        )
        query_log.append({
            "iteration": iteration,
            "tool": "note_relationship",
            "from": f"{args.get('from_table')}.{args.get('from_column')}",
            "to": f"{args.get('to_table')}.{args.get('to_column')}",
        })
        return {"stored": True, "note_id": note_id}
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "note_relationship",
            "error": str(e),
        })
        return {"error": str(e)}


async def handle_note_query_path(
    exploration_memory: Any,
    args: dict[str, Any],
    query_log: list[dict[str, Any]],
    iteration: int,
) -> dict[str, Any]:
    """Store a multi-step query recipe."""
    try:
        note_id = exploration_memory.note_query_path(
            question_pattern=args.get("question_pattern", ""),
            steps=args.get("steps", []),
            final_sql=args.get("final_sql", ""),
        )
        query_log.append({
            "iteration": iteration,
            "tool": "note_query_path",
            "pattern": args.get("question_pattern", "")[:80],
        })
        return {"stored": True, "note_id": note_id}
    except Exception as e:
        query_log.append({
            "iteration": iteration,
            "tool": "note_query_path",
            "error": str(e),
        })
        return {"error": str(e)}
