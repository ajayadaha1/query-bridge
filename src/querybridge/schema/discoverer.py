"""SchemaDiscoverer — Auto-discovers tables, columns, and relationships."""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from querybridge.connectors.base import DatabaseConnector
from querybridge.core.models import (
    ColumnInfo, Relationship, SchemaInfo, TableInfo, ValueCount,
)

logger = logging.getLogger("querybridge.schema.discoverer")


class SchemaDiscoverer:
    """Auto-discover database schema on first connect."""

    def __init__(self, connector: DatabaseConnector, sample_threshold: int = 100):
        self._connector = connector
        self._sample_threshold = sample_threshold

    async def discover(self) -> SchemaInfo:
        """Run full schema discovery."""
        logger.info("Starting schema discovery...")

        tables = await self._connector.get_tables()
        columns: Dict[str, List[ColumnInfo]] = {}
        sample_values: Dict[str, List[ValueCount]] = {}

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
        if "bool" in dtype:
            return True
        return False
