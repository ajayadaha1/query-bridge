"""RelationshipDetector — Detects FK/implicit joins via heuristics."""

from __future__ import annotations

import logging
import re
from typing import Dict, List, Set

from querybridge.connectors.base import DatabaseConnector
from querybridge.core.models import ColumnInfo, Relationship, SchemaInfo

logger = logging.getLogger("querybridge.schema.relationship_detector")


class RelationshipDetector:
    """Detects table relationships beyond explicit foreign keys."""

    def __init__(self, connector: DatabaseConnector):
        self._connector = connector

    async def detect(self, schema: SchemaInfo) -> List[Relationship]:
        """Detect additional relationships via naming heuristics."""
        existing = {
            (r.from_table, r.from_column, r.to_table, r.to_column)
            for r in schema.relationships
        }

        table_names = {t.name for t in schema.tables}
        pk_map: Dict[str, str] = {}
        for table in schema.tables:
            for col in schema.columns.get(table.name, []):
                if col.is_pk:
                    pk_map[table.name] = col.name

        inferred: List[Relationship] = []

        for table in schema.tables:
            for col in schema.columns.get(table.name, []):
                # Pattern: {other_table}_id
                match = re.match(r"^(.+)_id$", col.name)
                if not match:
                    continue

                candidate = match.group(1)

                # Direct match
                if candidate in table_names and candidate != table.name:
                    pk = pk_map.get(candidate, "id")
                    key = (table.name, col.name, candidate, pk)
                    if key not in existing:
                        inferred.append(Relationship(
                            from_table=table.name,
                            from_column=col.name,
                            to_table=candidate,
                            to_column=pk,
                            relationship_type="inferred_fk",
                            confidence=0.85,
                            join_hint=f"LEFT JOIN {candidate} ON {table.name}.{col.name} = {candidate}.{pk}",
                        ))

                # Plural to singular: orders -> order
                singular = candidate.rstrip("s")
                if singular in table_names and singular != table.name:
                    pk = pk_map.get(singular, "id")
                    key = (table.name, col.name, singular, pk)
                    if key not in existing:
                        inferred.append(Relationship(
                            from_table=table.name,
                            from_column=col.name,
                            to_table=singular,
                            to_column=pk,
                            relationship_type="inferred_fk",
                            confidence=0.80,
                            join_hint=f"LEFT JOIN {singular} ON {table.name}.{col.name} = {singular}.{pk}",
                        ))

        logger.debug(f"Detected {len(inferred)} inferred relationships")
        return inferred
