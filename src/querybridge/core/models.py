"""Request/response models for QueryBridge."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class QueryRequest:
    """A natural language query request."""
    question: str
    chat_id: str | None = None
    history: list[dict[str, Any]] | None = None

    def __post_init__(self):
        if self.chat_id is None:
            self.chat_id = str(uuid.uuid4())


@dataclass
class QueryLogEntry:
    """Record of a single SQL query executed during processing."""
    sql: str
    reason: str = ""
    row_count: int = 0
    execution_time_ms: int = 0
    blocked: bool = False
    error: str | None = None


@dataclass
class QueryResponse:
    """The complete response from QueryBridge."""
    answer: str
    chat_id: str
    query_log: list[dict[str, Any]] = field(default_factory=list)
    last_sql: str | None = None
    confidence: float = 0.0
    thinking_steps: list[dict[str, Any]] = field(default_factory=list)
    iterations_used: int = 0
    total_time_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "chat_id": self.chat_id,
            "query_log": self.query_log,
            "last_sql": self.last_sql,
            "confidence": self.confidence,
            "thinking_steps": self.thinking_steps,
            "iterations_used": self.iterations_used,
            "total_time_ms": self.total_time_ms,
        }


@dataclass
class TableInfo:
    """Metadata about a database table."""
    name: str
    table_type: str = "table"  # table, view, materialized_view
    row_count_estimate: int = 0
    comment: str | None = None


@dataclass
class ColumnInfo:
    """Metadata about a column."""
    name: str
    data_type: str
    nullable: bool = True
    is_pk: bool = False
    default: str | None = None
    comment: str | None = None


@dataclass
class Relationship:
    """A relationship between two tables."""
    from_table: str
    from_column: str
    to_table: str
    to_column: str
    relationship_type: str = "foreign_key"  # foreign_key, inferred_fk, value_overlap, ai_suggested
    confidence: float = 1.0
    join_hint: str = ""


@dataclass
class ValueCount:
    """A distinct value with its count."""
    value: Any
    count: int


@dataclass
class SchemaInfo:
    """Complete schema discovery result."""
    tables: list[TableInfo] = field(default_factory=list)
    columns: dict[str, list[ColumnInfo]] = field(default_factory=dict)
    relationships: list[Relationship] = field(default_factory=list)
    sample_values: dict[str, list[ValueCount]] = field(default_factory=dict)


@dataclass
class ToolDefinition:
    """Definition of a tool the LLM can call."""
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Any = None  # async callable
