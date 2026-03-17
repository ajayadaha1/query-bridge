"""Pluggable column hierarchy for escalation."""

from __future__ import annotations

from typing import List, Optional


class ColumnHierarchy:
    """Defines escalation paths for column selection.

    When a query returns 0 rows using one column, the strategy tracker
    can suggest the next column in the hierarchy.
    """

    def __init__(self, hierarchies: Optional[List[List[str]]] = None):
        self._hierarchies = hierarchies or []

    def get_next(self, tried_columns: List[str]) -> Optional[str]:
        """Get the next untried column in any hierarchy."""
        tried_set = set(c.lower() for c in tried_columns)
        for hierarchy in self._hierarchies:
            for col in hierarchy:
                if col.lower() not in tried_set:
                    return col
        return None

    def get_untried(self, tried_columns: List[str]) -> List[str]:
        """Get all untried columns across all hierarchies."""
        tried_set = set(c.lower() for c in tried_columns)
        untried = []
        for hierarchy in self._hierarchies:
            for col in hierarchy:
                if col.lower() not in tried_set and col not in untried:
                    untried.append(col)
        return untried

    def get_all_columns(self) -> List[str]:
        """Get all columns in all hierarchies."""
        all_cols = []
        for hierarchy in self._hierarchies:
            for col in hierarchy:
                if col not in all_cols:
                    all_cols.append(col)
        return all_cols
