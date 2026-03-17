"""Built-in tool handlers — wire tool calls to the DatabaseConnector."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from querybridge.connectors.base import DatabaseConnector
from querybridge.safety.guard import SQLGuard

logger = logging.getLogger("querybridge.agent.builtin_tools")

# Maximum result size in characters before truncation
MAX_RESULT_CHARS = 50_000


def _truncate_result(result: Dict[str, Any]) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
    """Quick COUNT(*) with optional conditions."""
    table_name = args.get("table_name", "")
    conditions = args.get("conditions")

    # Build a safe COUNT query
    dialect = connector.get_dialect_name()
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
    args: Dict[str, Any],
    query_log: List[Dict[str, Any]],
    iteration: int,
) -> Dict[str, Any]:
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
