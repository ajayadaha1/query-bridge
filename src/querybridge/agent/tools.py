"""Tool registry and built-in tool definitions for the agent loop."""

from __future__ import annotations

import json
import logging
from typing import Any, Callable, Coroutine, Dict, List, Optional

from querybridge.core.models import ToolDefinition

logger = logging.getLogger("querybridge.agent.tools")


# Type alias for async tool handler functions
ToolHandler = Callable[..., Coroutine[Any, Any, Dict[str, Any]]]


class ToolRegistry:
    """Registry of tools available to the LLM agent."""

    def __init__(self):
        self._tools: Dict[str, ToolDefinition] = {}
        self._handlers: Dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler):
        """Register a tool definition and its handler."""
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler
        logger.debug(f"Registered tool: {definition.name}")

    def get_handler(self, name: str) -> Optional[ToolHandler]:
        return self._handlers.get(name)

    def get_definitions(self) -> List[ToolDefinition]:
        return list(self._tools.values())

    def get_openai_tools(self) -> List[Dict[str, Any]]:
        """Return tool definitions in OpenAI function-calling format."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    @property
    def names(self) -> List[str]:
        return list(self._tools.keys())


# ============================================================================
# Built-in tool definitions (database-agnostic)
# ============================================================================

EXECUTE_SQL = ToolDefinition(
    name="execute_sql",
    description=(
        "Execute a read-only SQL SELECT query against the database. "
        "Returns columns and rows as JSON. Only SELECT/WITH queries are allowed."
    ),
    parameters={
        "type": "object",
        "properties": {
            "sql": {
                "type": "string",
                "description": "A SELECT query. Must be read-only.",
            },
            "reason": {
                "type": "string",
                "description": "Brief explanation of what this query checks.",
            },
        },
        "required": ["sql"],
    },
)

EXPLORE_TABLE = ToolDefinition(
    name="explore_table",
    description=(
        "Get an overview of a database table: column names, data types, row count, "
        "and sample rows. Use this FIRST to understand table structure."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_name": {
                "type": "string",
                "description": "Table name to explore.",
            },
        },
        "required": ["table_name"],
    },
)

GET_DISTINCT_VALUES = ToolDefinition(
    name="get_distinct_values",
    description=(
        "Get unique values of a column with occurrence counts. "
        "Essential for discovering exact enum values before writing WHERE clauses."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string", "description": "Table name."},
            "column": {"type": "string", "description": "Column name."},
            "limit": {
                "type": "integer",
                "description": "Max distinct values to return (default 25, max 50).",
            },
        },
        "required": ["table_name", "column"],
    },
)

VALIDATE_FILTER_VALUES = ToolDefinition(
    name="validate_filter_values",
    description=(
        "Check if specific values exist in a column. Returns exact matches and "
        "closest fuzzy matches. Use BEFORE writing a WHERE clause."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "values": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Values to look for.",
            },
        },
        "required": ["table_name", "column", "values"],
    },
)

COLUMN_PROFILE = ToolDefinition(
    name="column_profile",
    description=(
        "Get statistical profile of a column: NULL rate, distinct count, min/max, "
        "top values with counts."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "column": {"type": "string"},
            "where_clause": {
                "type": "string",
                "description": "Optional WHERE filter (without WHERE keyword).",
            },
        },
        "required": ["table_name", "column"],
    },
)

COUNT_ESTIMATE = ToolDefinition(
    name="count_estimate",
    description=(
        "Quick COUNT(*) with optional conditions. Use to estimate result size "
        "before running expensive queries."
    ),
    parameters={
        "type": "object",
        "properties": {
            "table_name": {"type": "string"},
            "conditions": {
                "type": "string",
                "description": "WHERE clause conditions (without WHERE keyword).",
            },
        },
        "required": ["table_name"],
    },
)

CROSS_VALIDATE = ToolDefinition(
    name="cross_validate",
    description=(
        "Run two SQL queries and compare results. Returns both results plus "
        "consistency check. Use after main query to verify results."
    ),
    parameters={
        "type": "object",
        "properties": {
            "primary_sql": {"type": "string", "description": "Main query to validate."},
            "check_sql": {"type": "string", "description": "Alternative query for consistency."},
            "comparison_note": {"type": "string", "description": "What consistency means."},
        },
        "required": ["primary_sql", "check_sql"],
    },
)


# All built-in tools
BUILTIN_TOOLS = [
    EXECUTE_SQL,
    EXPLORE_TABLE,
    GET_DISTINCT_VALUES,
    VALIDATE_FILTER_VALUES,
    COLUMN_PROFILE,
    COUNT_ESTIMATE,
    CROSS_VALIDATE,
]
