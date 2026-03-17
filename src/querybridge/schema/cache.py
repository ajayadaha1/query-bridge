"""SchemaCache — In-memory schema cache with TTL."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from querybridge.connectors.base import DatabaseConnector
from querybridge.core.models import ColumnInfo, Relationship, SchemaInfo, TableInfo, ValueCount
from querybridge.plugins.base import DomainPlugin
from querybridge.schema.discoverer import SchemaDiscoverer
from querybridge.schema.relationship_detector import RelationshipDetector

logger = logging.getLogger("querybridge.schema.cache")


class SchemaCache:
    """Cached schema with TTL-based expiration."""

    def __init__(
        self,
        connector: DatabaseConnector,
        plugin: Optional[DomainPlugin] = None,
        ttl_seconds: int = 300,
    ):
        self._connector = connector
        self._plugin = plugin
        self._ttl = ttl_seconds
        self._schema: Optional[SchemaInfo] = None
        self._schema_text: Optional[str] = None
        self._cached_at: float = 0

    async def get_schema(self, force_refresh: bool = False) -> SchemaInfo:
        """Get the discovered schema, refreshing if expired."""
        now = time.monotonic()
        if not force_refresh and self._schema and (now - self._cached_at) < self._ttl:
            return self._schema

        discoverer = SchemaDiscoverer(self._connector)
        self._schema = await discoverer.discover()

        # Detect additional relationships via heuristics
        detector = RelationshipDetector(self._connector)
        inferred = await detector.detect(self._schema)
        self._schema.relationships.extend(inferred)

        self._schema_text = None  # Invalidate text cache
        self._cached_at = time.monotonic()
        return self._schema

    async def get_schema_context(self, force_refresh: bool = False) -> str:
        """Get a compact text representation for LLM prompt injection."""
        schema = await self.get_schema(force_refresh)

        if self._schema_text and not force_refresh:
            return self._schema_text

        parts = []
        annotations = {}
        if self._plugin:
            annotations = self._plugin.get_column_annotations()

        for table in schema.tables:
            cols = schema.columns.get(table.name, [])
            parts.append(f"\n**{table.name}** ({table.row_count_estimate} rows)")
            for col in cols:
                flags = []
                if col.is_pk:
                    flags.append("PK")
                if not col.nullable:
                    flags.append("NOT NULL")

                # Check relationships
                for rel in schema.relationships:
                    if rel.from_table == table.name and rel.from_column == col.name:
                        flags.append(f"→ {rel.to_table}.{rel.to_column}")

                flag_str = f" [{', '.join(flags)}]" if flags else ""

                # Sample values
                key = f"{table.name}.{col.name}"
                sample = ""
                if key in schema.sample_values:
                    vals = schema.sample_values[key][:5]
                    sample = f" [{', '.join(str(v.value) for v in vals)}]"

                # Annotation
                ann = annotations.get(col.name, "")
                ann_str = f" — {ann}" if ann else ""

                parts.append(f"  - {col.name}: {col.data_type}{flag_str}{sample}{ann_str}")

        # Relationships summary
        if schema.relationships:
            parts.append("\n### Relationships")
            for rel in schema.relationships:
                conf = f" ({rel.confidence*100:.0f}%)" if rel.confidence < 1.0 else ""
                parts.append(
                    f"  - {rel.from_table}.{rel.from_column} → "
                    f"{rel.to_table}.{rel.to_column} ({rel.relationship_type}){conf}"
                )

        self._schema_text = "\n".join(parts)
        return self._schema_text

    def invalidate(self):
        """Force cache invalidation."""
        self._schema = None
        self._schema_text = None
        self._cached_at = 0
