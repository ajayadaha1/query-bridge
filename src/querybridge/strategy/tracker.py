"""StrategyTracker — Tracks investigation approaches during the agentic loop.

Prevents repetition of failed strategies and suggests escalation paths.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from querybridge.strategy.column_hierarchy import ColumnHierarchy

logger = logging.getLogger("querybridge.strategy.tracker")


def extract_columns_from_sql(sql: str) -> List[str]:
    """Extract column names referenced in a SQL query."""
    if not sql:
        return []
    columns: Set[str] = set()
    normalized = " ".join(sql.split())

    sql_keywords = {
        "and", "or", "not", "where", "select", "from", "null", "join", "on",
        "inner", "left", "right", "outer", "group", "by", "order", "having",
        "limit", "offset", "as", "case", "when", "then", "else", "end", "with",
        "union", "intersect", "except", "between", "exists", "all", "any",
    }

    # table.column references
    for match in re.finditer(r"\b\w+\.(\w+)\b", normalized):
        columns.add(match.group(1).lower())

    # WHERE clause columns
    for match in re.finditer(
        r"\b(\w+)\s*(?:=|!=|<>|>=|<=|>|<)\s*|(\w+)\s+(?:ILIKE|LIKE|IN|IS\s+(?:NOT\s+)?NULL)\s",
        normalized, re.IGNORECASE,
    ):
        col = (match.group(1) or match.group(2) or "").lower()
        if col and col not in sql_keywords:
            columns.add(col)

    return sorted(columns)


def extract_filter_patterns_from_sql(sql: str) -> List[str]:
    """Extract filter patterns from WHERE clause."""
    if not sql:
        return []
    patterns = []
    normalized = " ".join(sql.split())

    for match in re.finditer(r"(\w+)\s*=\s*'([^']+)'", normalized, re.IGNORECASE):
        patterns.append(f"{match.group(1)} = '{match.group(2)}'")
    for match in re.finditer(r"(\w+)\s+ILIKE\s+'([^']+)'", normalized, re.IGNORECASE):
        patterns.append(f"{match.group(1)} ILIKE '{match.group(2)}'")
    for match in re.finditer(r"(\w+)\s+IN\s*\(([^)]+)\)", normalized, re.IGNORECASE):
        patterns.append(f"{match.group(1)} IN ({match.group(2).strip()})")

    return patterns


@dataclass
class StrategyEntry:
    """Record of a single investigation approach."""
    iteration: int
    approach: str
    columns_used: List[str]
    filter_patterns: List[str]
    result_count: int
    success: bool
    notes: str = ""
    sql: Optional[str] = None

    def get_status_label(self) -> str:
        if not self.success:
            return "FAILED"
        if self.success and 0 < self.result_count <= 2:
            return "SUSPECT"
        return "SUCCESS"


class StrategyTracker:
    """Tracks investigation strategies during the agentic loop."""

    def __init__(self, column_hierarchy: Optional[ColumnHierarchy] = None):
        self.entries: List[StrategyEntry] = []
        self._tried_combinations: Set[Tuple[str, str]] = set()
        self._column_hierarchy = column_hierarchy or ColumnHierarchy()

    @property
    def error_count(self) -> int:
        return sum(1 for e in self.entries if not e.success)

    def record_attempt(
        self, iteration: int, approach: str, sql: str,
        result_count: int, success: bool, notes: str = "",
    ) -> StrategyEntry:
        columns = extract_columns_from_sql(sql)
        filters = extract_filter_patterns_from_sql(sql)

        entry = StrategyEntry(
            iteration=iteration, approach=approach,
            columns_used=columns, filter_patterns=filters,
            result_count=result_count, success=success,
            notes=notes, sql=sql,
        )
        self.entries.append(entry)

        hier_cols = set(self._column_hierarchy.get_all_columns())
        for col in columns:
            if col in hier_cols:
                for pattern in filters:
                    if col.lower() in pattern.lower():
                        self._tried_combinations.add((col, pattern))

        return entry

    def get_tried_columns(self) -> List[str]:
        tried = set()
        hier_cols = set(c.lower() for c in self._column_hierarchy.get_all_columns())
        for entry in self.entries:
            for col in entry.columns_used:
                if col.lower() in hier_cols:
                    tried.add(col)
        return sorted(tried)

    def suggest_next(self) -> str:
        untried = self._column_hierarchy.get_untried(self.get_tried_columns())
        if not untried:
            return "All columns in the hierarchy have been tried."
        return f"Try `{untried[0]}` next."

    def should_escalate(self) -> bool:
        if not self.entries:
            return False
        last = self.entries[-1]
        untried = self._column_hierarchy.get_untried(self.get_tried_columns())
        return (not last.success or (last.success and last.result_count <= 2)) and len(untried) > 0

    def get_status_summary(self, max_entries: int = 10) -> str:
        if not self.entries:
            return "No strategies tried yet."
        lines = ["Tried:"]
        recent = self.entries[-max_entries:]
        for entry in recent:
            filter_str = entry.filter_patterns[0] if entry.filter_patterns else "no filter"
            lines.append(
                f"  ({entry.iteration}) {filter_str} -> {entry.result_count} rows [{entry.get_status_label()}]"
            )
        untried = self._column_hierarchy.get_untried(self.get_tried_columns())
        if untried:
            lines.append(f"Not yet tried: {', '.join(untried)}")
        return "\n".join(lines)

    def reset(self):
        self.entries.clear()
        self._tried_combinations.clear()
