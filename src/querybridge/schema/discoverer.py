"""SchemaDiscoverer — Auto-discovers tables, columns, and relationships."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from querybridge.core.models import (
    ColumnInfo,
    SchemaIndex,
    SchemaInfo,
    ValueCount,
)

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector

logger = logging.getLogger("querybridge.schema.discoverer")

# Threshold: databases with this many tables or more use lazy discovery
LAZY_THRESHOLD = 20


class SchemaDiscoverer:
    """Auto-discover database schema on first connect."""

    def __init__(self, connector: DatabaseConnector, sample_threshold: int = 100):
        self._connector = connector
        self._sample_threshold = sample_threshold

    async def discover_index(self) -> SchemaIndex:
        """Tier 1: Build a lightweight table→columns index via ONE metadata query.

        Returns in ~1-2 seconds even for 200+ table databases. The index
        is enough for the LLM to know what exists and use search_schema()
        to find relevant tables on demand.
        """
        logger.info("Starting fast schema index discovery (Tier 1)...")

        dialect = self._connector.get_dialect_name()

        # Single metadata query — dialect-aware for best performance
        try:
            if dialect == "snowflake":
                result = await self._connector.execute(
                    "SELECT table_name, column_name, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_schema = CURRENT_SCHEMA() "
                    "ORDER BY table_name, ordinal_position",
                    max_rows=10000,
                )
            else:
                result = await self._connector.execute(
                    "SELECT table_name, column_name, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
                    "ORDER BY table_name, ordinal_position",
                    max_rows=10000,
                )
        except Exception:
            # Fallback for SQLite / dialects without information_schema
            return await self._discover_index_fallback()

        tables: dict[str, list[str]] = {}
        column_types: dict[str, str] = {}
        total_cols = 0

        for row in result.rows:
            tname = row.get("table_name") or row.get("TABLE_NAME", "")
            cname = row.get("column_name") or row.get("COLUMN_NAME", "")
            dtype = row.get("data_type") or row.get("DATA_TYPE", "")
            if not tname or not cname:
                continue
            tables.setdefault(tname, []).append(cname)
            column_types[f"{tname}.{cname}"] = dtype
            total_cols += 1

        index = SchemaIndex(
            tables=tables,
            column_types=column_types,
            table_count=len(tables),
            total_column_count=total_cols,
        )
        logger.info(
            f"Schema index ready: {index.table_count} tables, "
            f"{index.total_column_count} columns"
        )
        return index

    async def _discover_index_fallback(self) -> SchemaIndex:
        """Fallback for SQLite: use get_tables + get_columns (still fast for small DBs)."""
        logger.info("Falling back to sequential index build...")
        table_objs = await self._connector.get_tables()
        tables: dict[str, list[str]] = {}
        column_types: dict[str, str] = {}
        total_cols = 0

        for t in table_objs:
            cols = await self._connector.get_columns(t.name)
            tables[t.name] = [c.name for c in cols]
            for c in cols:
                column_types[f"{t.name}.{c.name}"] = c.data_type
                total_cols += 1

        return SchemaIndex(
            tables=tables,
            column_types=column_types,
            table_count=len(tables),
            total_column_count=total_cols,
        )

    async def discover(self) -> SchemaInfo:
        """Run full schema discovery (Tier 2)."""
        logger.info("Starting schema discovery...")

        tables = await self._connector.get_tables()
        columns: dict[str, list[ColumnInfo]] = {}
        sample_values: dict[str, list[ValueCount]] = {}

        for table in tables:
            cols = await self._connector.get_columns(table.name)
            columns[table.name] = cols

            # Sample categorical columns
            for col in cols:
                if self._is_categorical(col):
                    try:
                        values = await self._connector.get_distinct_values(
                            table.name, col.name, limit=25
                        )
                        if values:
                            key = f"{table.name}.{col.name}"
                            sample_values[key] = values
                    except Exception as e:
                        logger.debug(f"Failed to sample {table.name}.{col.name}: {e}")

        relationships = await self._connector.get_relationships()

        logger.info(
            f"Schema discovery complete: {len(tables)} tables, "
            f"{sum(len(c) for c in columns.values())} columns, "
            f"{len(relationships)} relationships"
        )

        return SchemaInfo(
            tables=tables,
            columns=columns,
            relationships=relationships,
            sample_values=sample_values,
        )

    def _is_categorical(self, col: ColumnInfo) -> bool:
        """Heuristic: is this column likely categorical (worth sampling)?"""
        dtype = col.data_type.lower()
        if any(t in dtype for t in ("varchar", "text", "char", "enum")):
            return True
        return "bool" in dtype
