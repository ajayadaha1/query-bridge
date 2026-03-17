"""Abstract base class for database connectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from querybridge.core.models import (
        ColumnInfo,
        Relationship,
        TableInfo,
        ValueCount,
    )


class QueryResult:
    """Result of a SQL query execution."""

    __slots__ = ("columns", "rows", "row_count", "truncated", "execution_time_ms")

    def __init__(
        self,
        columns: list[str],
        rows: list[dict[str, Any]],
        row_count: int,
        truncated: bool = False,
        execution_time_ms: int = 0,
    ):
        self.columns = columns
        self.rows = rows
        self.row_count = row_count
        self.truncated = truncated
        self.execution_time_ms = execution_time_ms

    def to_dict(self) -> dict[str, Any]:
        return {
            "columns": self.columns,
            "rows": self.rows,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "execution_time_ms": self.execution_time_ms,
        }


class DatabaseConnector(ABC):
    """Abstract database connector — each dialect implements this."""

    @abstractmethod
    async def execute(self, sql: str, max_rows: int = 500) -> QueryResult:
        """Execute a read-only SQL query and return results."""

    @abstractmethod
    async def get_tables(self) -> list[TableInfo]:
        """List all accessible tables/views."""

    @abstractmethod
    async def get_columns(self, table: str) -> list[ColumnInfo]:
        """Get column metadata for a table."""

    @abstractmethod
    async def get_distinct_values(
        self, table: str, column: str, limit: int = 25
    ) -> list[ValueCount]:
        """Get distinct values with counts for a column."""

    @abstractmethod
    async def get_row_count(
        self, table: str, where: str | None = None
    ) -> int:
        """Get row count, optionally with a WHERE clause."""

    @abstractmethod
    async def get_sample_rows(
        self, table: str, limit: int = 3
    ) -> list[dict[str, Any]]:
        """Get sample rows from a table."""

    @abstractmethod
    async def get_relationships(self) -> list[Relationship]:
        """Discover foreign key and inferred relationships."""

    @abstractmethod
    def get_dialect_name(self) -> str:
        """Return dialect identifier: 'postgresql', 'snowflake', 'mysql', etc."""

    @abstractmethod
    async def close(self):
        """Clean up connection pool."""

    # Convenience methods with default implementations

    async def explore_table(self, table: str) -> dict[str, Any]:
        """Return table overview: columns, types, row count, and sample rows."""
        columns = await self.get_columns(table)
        row_count = await self.get_row_count(table)
        samples = await self.get_sample_rows(table)
        return {
            "table": table,
            "row_count": row_count,
            "columns": [
                {"name": c.name, "type": c.data_type, "nullable": c.nullable}
                for c in columns
            ],
            "sample_rows": samples,
        }

    async def column_profile(
        self, table: str, column: str, where: str | None = None
    ) -> dict[str, Any]:
        """Get statistical profile of a column."""
        where_sql = f"WHERE {where}" if where else ""
        stats_sql = (
            f'SELECT COUNT(*) AS total_rows, '
            f'COUNT("{column}") AS non_null_count, '
            f'COUNT(DISTINCT "{column}") AS distinct_count, '
            f'MIN("{column}"::text) AS min_val, '
            f'MAX("{column}"::text) AS max_val '
            f"FROM {table} {where_sql}"
        )
        result = await self.execute(stats_sql)
        if not result.rows:
            return {"error": "No statistics returned"}

        stats = result.rows[0]
        total = stats.get("total_rows", 0) or 0
        non_null = stats.get("non_null_count", 0) or 0
        null_count = total - non_null
        null_pct = round((null_count / total * 100), 2) if total > 0 else 0

        top_sql = (
            f'SELECT "{column}"::text AS value, COUNT(*) AS count '
            f"FROM {table} {where_sql} "
            f'GROUP BY "{column}" ORDER BY count DESC LIMIT 10'
        )
        top_result = await self.execute(top_sql)

        return {
            "table": table, "column": column,
            "total_rows": total,
            "null_count": null_count, "null_pct": null_pct,
            "distinct_count": stats.get("distinct_count", 0) or 0,
            "min": stats.get("min_val"), "max": stats.get("max_val"),
            "top_values": top_result.rows,
        }
