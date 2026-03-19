"""Tool registry and built-in tool definitions for the agent loop."""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

from querybridge.core.models import ToolDefinition

logger = logging.getLogger("querybridge.agent.tools")


# Type alias for async tool handler functions
ToolHandler = Callable[..., Coroutine[Any, Any, dict[str, Any]]]


class ToolRegistry:
    """Registry of tools available to the LLM agent."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}
        self._handlers: dict[str, ToolHandler] = {}

    def register(self, definition: ToolDefinition, handler: ToolHandler):
        """Register a tool definition and its handler."""
        self._tools[definition.name] = definition
        self._handlers[definition.name] = handler
        logger.debug(f"Registered tool: {definition.name}")

    def get_handler(self, name: str) -> ToolHandler | None:
        return self._handlers.get(name)

    def get_definitions(self) -> list[ToolDefinition]:
        return list(self._tools.values())

    def get_openai_tools(self) -> list[dict[str, Any]]:
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
    def names(self) -> list[str]:
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

SEARCH_SCHEMA = ToolDefinition(
    name="search_schema",
    description=(
        "Search the database schema index for tables and columns matching keywords. "
        "Returns matching table names and their columns. Use this to find relevant "
        "tables before calling explore_table() or writing SQL. Supports fuzzy matching."
    ),
    parameters={
        "type": "object",
        "properties": {
            "keywords": {
                "type": "string",
                "description": (
                    "Space-separated search terms to match against table and column names. "
                    "Example: 'serial number asset' or 'customer order'."
                ),
            },
        },
        "required": ["keywords"],
    },
)


# Exploration memory tools — agent notes what it discovers

RECALL_EXPLORATIONS = ToolDefinition(
    name="recall_explorations",
    description=(
        "Search your exploration memory for notes about tables, columns, relationships, "
        "or query patterns you have previously discovered. Use this to check what you "
        "already know before exploring from scratch."
    ),
    parameters={
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": (
                    "What you want to recall. Can be a table name, column name, "
                    "concept, or question pattern. Example: 'CIP trace snowflake' "
                    "or 'PPIN_LOOKUP safety'."
                ),
            },
            "note_types": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Optional filter by note type: table_profile, column_relevance, "
                    "relationship, query_path, schema_map, routing_outcome, "
                    "safety_warning, negative_knowledge."
                ),
            },
        },
        "required": ["topic"],
    },
)

NOTE_EXPLORATION = ToolDefinition(
    name="note_exploration",
    description=(
        "Write a note to your persistent exploration memory. Notes survive across "
        "conversations. Use this after discovering something useful (table profile, "
        "column relevance, safety warning) so you remember it next time."
    ),
    parameters={
        "type": "object",
        "properties": {
            "subject": {
                "type": "string",
                "description": "Table name, schema, or topic this note is about.",
            },
            "observation": {
                "type": "string",
                "description": (
                    "What you discovered. Be specific: include table names, column names, "
                    "row counts, data types, gotchas. Write as if talking to your future self."
                ),
            },
            "note_type": {
                "type": "string",
                "enum": [
                    "table_profile", "column_relevance", "schema_map",
                    "safety_warning", "negative_knowledge",
                ],
                "description": "Category of this note.",
            },
        },
        "required": ["subject", "observation", "note_type"],
    },
)

NOTE_RELATIONSHIP = ToolDefinition(
    name="note_relationship",
    description=(
        "Record a discovered JOIN relationship between two tables. Use this when you "
        "notice shared column names across tables or successfully execute a JOIN."
    ),
    parameters={
        "type": "object",
        "properties": {
            "from_table": {"type": "string", "description": "Source table name."},
            "from_column": {"type": "string", "description": "Source column name."},
            "to_table": {"type": "string", "description": "Target table name."},
            "to_column": {"type": "string", "description": "Target column name."},
            "notes": {
                "type": "string",
                "description": "Description of the relationship and when to use this join.",
            },
        },
        "required": ["from_table", "from_column", "to_table", "to_column"],
    },
)

NOTE_QUERY_PATH = ToolDefinition(
    name="note_query_path",
    description=(
        "Save a multi-step query recipe that worked. Use this after solving a "
        "question that required multiple steps (explore → intermediate query → final query). "
        "Future similar questions will benefit from this saved recipe."
    ),
    parameters={
        "type": "object",
        "properties": {
            "question_pattern": {
                "type": "string",
                "description": "A short description of the question type this recipe solves.",
            },
            "steps": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Ordered list of steps to solve this type of question.",
            },
            "final_sql": {
                "type": "string",
                "description": "The final SQL query that answered the question.",
            },
        },
        "required": ["question_pattern", "steps"],
    },
)

# Exploration tools (registered alongside builtins when ExplorationMemory is available)
EXPLORATION_TOOLS = [
    RECALL_EXPLORATIONS,
    NOTE_EXPLORATION,
    NOTE_RELATIONSHIP,
    NOTE_QUERY_PATH,
]

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
