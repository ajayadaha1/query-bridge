"""SchemaCache — Two-tier schema cache: fast index + optional full discovery.

Tier 1 (lazy): ONE metadata query → table+column index (~2s, any DB size).
Tier 2 (full): Complete discovery with sampling (current behavior, <20 tables).

Databases with ≥20 tables automatically use lazy mode. The LLM gets a compact
schema index in the system prompt and uses search_schema() to find tables.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from querybridge.schema.discoverer import LAZY_THRESHOLD, SchemaDiscoverer
from querybridge.schema.relationship_detector import RelationshipDetector

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector
    from querybridge.core.models import SchemaIndex, SchemaInfo
    from querybridge.plugins.base import DomainPlugin

logger = logging.getLogger("querybridge.schema.cache")


class SchemaCache:
    """Cached schema with TTL-based expiration and two-tier discovery."""

    def __init__(
        self,
        connector: DatabaseConnector,
        plugin: DomainPlugin | None = None,
        ttl_seconds: int = 300,
        cache_dir: str | None = None,
    ):
        self._connector = connector
        self._plugin = plugin
        self._ttl = ttl_seconds

        # Full schema (Tier 2)
        self._schema: SchemaInfo | None = None
        self._schema_text: str | None = None
        self._cached_at: float = 0

        # Schema index (Tier 1)
        self._index: SchemaIndex | None = None
        self._index_text: str | None = None
        self._index_cached_at: float = 0

        # Mode: None (not determined), "full", or "lazy"
        self._mode: str | None = None

        # Persistence directory
        self._cache_dir = Path(cache_dir) if cache_dir else None

    @property
    def is_lazy(self) -> bool:
        """Whether this cache is operating in lazy (index-only) mode."""
        return self._mode == "lazy"

    @property
    def schema_index(self) -> SchemaIndex | None:
        """The lightweight schema index (Tier 1). Available in both modes."""
        return self._index

    async def initialize(self) -> str:
        """Initialize the cache: discover index, auto-select mode.

        Returns the mode selected: 'full' or 'lazy'.
        """
        # Always start with the fast index
        discoverer = SchemaDiscoverer(self._connector)

        # Try loading persisted index first
        loaded = self._load_index_from_disk()
        if loaded:
            self._index = loaded
            self._index_cached_at = time.monotonic()
            logger.info(f"Loaded persisted schema index: {loaded.table_count} tables")
        else:
            self._index = await discoverer.discover_index()
            self._index_cached_at = time.monotonic()
            self._save_index_to_disk()

        # Auto-select mode based on table count
        if self._index.table_count >= LAZY_THRESHOLD:
            self._mode = "lazy"
            logger.info(
                f"Lazy mode: {self._index.table_count} tables "
                f"(≥{LAZY_THRESHOLD} threshold). Using schema index + search_schema tool."
            )
        else:
            self._mode = "full"
            logger.info(
                f"Full mode: {self._index.table_count} tables "
                f"(<{LAZY_THRESHOLD} threshold). Running full discovery."
            )
            # Eagerly run full discovery for small databases
            await self.get_schema()

        self._index_text = None  # Invalidate cached text
        return self._mode

    async def get_schema(self, force_refresh: bool = False) -> SchemaInfo:
        """Get the full discovered schema, refreshing if expired."""
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

    async def get_index(self, force_refresh: bool = False) -> SchemaIndex:
        """Get the lightweight schema index (Tier 1)."""
        now = time.monotonic()
        if (
            not force_refresh
            and self._index
            and (now - self._index_cached_at) < self._ttl
        ):
            return self._index

        discoverer = SchemaDiscoverer(self._connector)
        self._index = await discoverer.discover_index()
        self._index_cached_at = time.monotonic()
        self._index_text = None
        self._save_index_to_disk()
        return self._index

    async def get_schema_context(self, force_refresh: bool = False) -> str:
        """Get text for LLM prompt injection.

        In full mode: returns complete schema with columns, types, samples.
        In lazy mode: returns compact index (table list with column names).
        """
        if self._mode == "lazy":
            return await self.get_index_context(force_refresh)
        return await self._get_full_schema_context(force_refresh)

    async def get_index_context(self, force_refresh: bool = False) -> str:
        """Compact schema index text for lazy mode (~3KB even for 200 tables)."""
        index = await self.get_index(force_refresh)

        if self._index_text and not force_refresh:
            return self._index_text

        dialect = self._connector.get_dialect_name().upper()
        parts = [
            f"Connected to a **{dialect}** database with "
            f"**{index.table_count} tables** and "
            f"**{index.total_column_count} columns**.\n",
            "⚠️ This is a SCHEMA INDEX only — it lists the tables discovered in the "
            "current schema. The database may contain additional tables in other schemas. "
            "To get a complete table list, query `INFORMATION_SCHEMA.TABLES` directly.\n",
            "Use `search_schema(keywords)` to find relevant tables, "
            "then `explore_table(table_name)` for full details.\n",
            "### Table Index",
        ]

        for table_name in sorted(index.tables.keys()):
            cols = index.tables[table_name]
            col_str = ", ".join(cols[:12])  # Cap at 12 columns per line
            if len(cols) > 12:
                col_str += f", ... (+{len(cols) - 12} more)"
            parts.append(f"- **{table_name}**: {col_str}")

        self._index_text = "\n".join(parts)
        return self._index_text

    async def _get_full_schema_context(self, force_refresh: bool = False) -> str:
        """Full schema text (original behavior) for small databases."""
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

                parts.append(
                    f"  - {col.name}: {col.data_type}{flag_str}{sample}{ann_str}"
                )

        # Relationships summary
        if schema.relationships:
            parts.append("\n### Relationships")
            for rel in schema.relationships:
                conf = (
                    f" ({rel.confidence * 100:.0f}%)" if rel.confidence < 1.0 else ""
                )
                parts.append(
                    f"  - {rel.from_table}.{rel.from_column} → "
                    f"{rel.to_table}.{rel.to_column}{conf}"
                )

        self._schema_text = "\n".join(parts)
        return self._schema_text

    # ---- Persistence ----

    def _get_index_path(self) -> Path | None:
        """Get the file path for persisted schema index."""
        if not self._cache_dir:
            return None
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        dialect = self._connector.get_dialect_name()
        return self._cache_dir / f"schema_index_{dialect}.json"

    def _save_index_to_disk(self) -> None:
        """Persist the schema index to JSON."""
        path = self._get_index_path()
        if not path or not self._index:
            return
        try:
            data = {
                "tables": self._index.tables,
                "column_types": self._index.column_types,
                "table_count": self._index.table_count,
                "total_column_count": self._index.total_column_count,
                "saved_at": time.time(),
            }
            path.write_text(json.dumps(data, indent=2))
            logger.info(f"Schema index persisted to {path}")
        except Exception as e:
            logger.warning(f"Failed to persist schema index: {e}")

    def _load_index_from_disk(self) -> SchemaIndex | None:
        """Load a persisted schema index if fresh enough."""
        from querybridge.core.models import SchemaIndex

        path = self._get_index_path()
        if not path or not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            saved_at = data.get("saved_at", 0)
            # Treat persisted index as valid for 1 hour
            if time.time() - saved_at > 3600:
                logger.info("Persisted schema index expired, will re-discover")
                return None
            return SchemaIndex(
                tables=data["tables"],
                column_types=data.get("column_types", {}),
                table_count=data["table_count"],
                total_column_count=data["total_column_count"],
            )
        except Exception as e:
            logger.warning(f"Failed to load persisted schema index: {e}")
            return None
