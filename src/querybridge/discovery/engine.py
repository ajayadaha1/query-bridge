"""DiscoveryEngine — Pre-flight entity verification against live DB.

Runs BEFORE the LLM loop to verify filter values exist in the database.
This is pure SQL — fast, deterministic, and cheap (uses 0 LLM iterations).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from querybridge.discovery.brief import DiscoveryBrief, FilterVerification
from querybridge.discovery.fuzzy_match import fuzzy_ratio, normalize_value

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector

logger = logging.getLogger("querybridge.discovery.engine")

DEFAULT_FUZZY_THRESHOLD = 0.5


class DiscoveryEngine:
    """Pre-flight discovery engine that verifies filter values before LLM execution."""

    def __init__(
        self,
        connector: DatabaseConnector,
        entity_column_map: dict[str, list[str]] | None = None,
        primary_table: str | None = None,
        fuzzy_threshold: float = DEFAULT_FUZZY_THRESHOLD,
    ):
        self._connector = connector
        self._entity_column_map = entity_column_map or {}
        self._primary_table = primary_table
        self._fuzzy_threshold = fuzzy_threshold
        self._distinct_cache: dict[str, list[tuple[str, int]]] = {}

    async def run_discovery(
        self,
        entities: list[str],
    ) -> DiscoveryBrief:
        """Run pre-flight discovery for a list of entities.

        Args:
            entities: Entity strings from classifier, e.g.:
                ["customer:Alibaba", "error_amd:FP_PRF"]
        """
        brief = DiscoveryBrief()

        if not entities:
            return brief

        parsed = self._parse_entities(entities)

        tasks = []
        for entity_type, entity_value in parsed:
            columns = self._entity_column_map.get(entity_type, [])
            if columns:
                tasks.append(self._verify_entity(entity_type, entity_value, columns))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, BaseException):
                logger.warning(f"Discovery failed: {result}")
                continue
            if result:
                verification, suggestion = result
                brief.verified_filters.append(verification)
                if suggestion:
                    brief.suggested_corrections.append(suggestion)

        return brief

    def _parse_entities(self, entities: list[str]) -> list[tuple[str, str]]:
        parsed = []
        for entity in entities:
            if ":" in entity:
                parts = entity.split(":", 1)
                parsed.append((parts[0].strip().lower(), parts[1].strip()))
            else:
                parsed.append(("unknown", entity.strip()))
        return parsed

    async def _verify_entity(
        self, entity_type: str, entity_value: str, columns: list[str],
    ) -> tuple[FilterVerification, dict[str, Any] | None] | None:
        """Verify an entity value against candidate columns."""
        all_fuzzy = []

        for column in columns:
            try:
                distinct = await self._get_distinct_cached(column)
            except Exception:
                continue
            if not distinct:
                continue

            normalized_search = normalize_value(entity_value)
            for db_value, count in distinct:
                if db_value is None:
                    continue
                if normalize_value(str(db_value)) == normalized_search:
                    return (
                        FilterVerification(
                            column=column, value=str(db_value),
                            status="exact_match", row_count=count,
                            closest_matches=[(str(db_value), count)],
                        ),
                        None,
                    )

                ratio = fuzzy_ratio(entity_value, str(db_value))
                if ratio >= self._fuzzy_threshold:
                    all_fuzzy.append((column, str(db_value), count, ratio))

        if all_fuzzy:
            best = max(all_fuzzy, key=lambda x: x[3])
            col, val, count, _ = best
            matches = sorted(
                [(v, c, r) for cl, v, c, r in all_fuzzy if cl == col],
                key=lambda x: (-x[2], -x[1]),
            )[:3]
            return (
                FilterVerification(
                    column=col, value=entity_value, status="fuzzy_match",
                    row_count=count, closest_matches=[(m[0], m[1]) for m in matches],
                ),
                {"asked": entity_value, "column": col,
                 "closest": [(m[0], m[1]) for m in matches],
                 "suggestion": f"Use {col} = '{val}'"},
            )

        first_col = columns[0] if columns else "unknown"
        return (
            FilterVerification(column=first_col, value=entity_value, status="not_found"),
            {"asked": entity_value, "column": first_col, "closest": [],
             "suggestion": f"Value '{entity_value}' not found. Check spelling or explore distinct values."},
        )

    async def _get_distinct_cached(self, column: str, limit: int = 50) -> list[tuple[str, int]]:
        if column in self._distinct_cache:
            return self._distinct_cache[column]

        if not self._primary_table:
            return []

        values = await self._connector.get_distinct_values(
            self._primary_table, column, limit=limit
        )
        result = [(v.value, v.count) for v in values]
        self._distinct_cache[column] = result
        return result

    def format_brief_for_prompt(self, brief: DiscoveryBrief) -> str:
        """Format the discovery brief for injection into the system prompt."""
        if not brief.verified_filters and not brief.suggested_corrections:
            return ""

        lines = [
            "## Pre-Flight Discovery (auto-generated)",
            "Your question references these entities:",
        ]

        for vf in brief.verified_filters:
            if vf.status == "exact_match":
                lines.append(f'- {vf.column} "{vf.value}" -> VERIFIED ({vf.row_count} rows)')
            elif vf.status == "fuzzy_match":
                closest_str = ", ".join(f"'{m[0]}' ({m[1]} rows)" for m in vf.closest_matches[:3])
                lines.append(f'- "{vf.value}" -> NOT EXACT in {vf.column}. Closest: {closest_str}')
            else:
                lines.append(f'- "{vf.value}" -> NOT FOUND. Use get_distinct_values() to explore.')

        if brief.suggested_corrections:
            lines.append("\n**Recommendations:**")
            for s in brief.suggested_corrections:
                lines.append(f"- {s['suggestion']}")

        if brief.total_row_estimate > 0:
            lines.append(f"\nEstimated result size: ~{brief.total_row_estimate} rows")

        return "\n".join(lines)

    def clear_cache(self):
        self._distinct_cache.clear()
