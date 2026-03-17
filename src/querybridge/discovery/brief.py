"""DiscoveryBrief — Pre-flight discovery result model."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FilterVerification:
    """Result of verifying a single filter value against the database."""
    column: str
    value: str
    status: str  # "exact_match" | "fuzzy_match" | "not_found"
    closest_matches: list[tuple[str, int]] = field(default_factory=list)
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column, "value": self.value, "status": self.status,
            "closest_matches": [{"value": v, "count": c} for v, c in self.closest_matches],
            "row_count": self.row_count,
        }


@dataclass
class DiscoveryBrief:
    """Complete discovery results for injection into system prompt."""
    verified_filters: list[FilterVerification] = field(default_factory=list)
    suggested_corrections: list[dict[str, Any]] = field(default_factory=list)
    total_row_estimate: int = 0
    data_quality_warnings: list[str] = field(default_factory=list)
    table_coverage: dict[str, int] = field(default_factory=dict)

    @property
    def all_filters_verified(self) -> bool:
        return all(f.status == "exact_match" for f in self.verified_filters) if self.verified_filters else True

    def to_dict(self) -> dict[str, Any]:
        return {
            "verified_filters": [f.to_dict() for f in self.verified_filters],
            "suggested_corrections": self.suggested_corrections,
            "total_row_estimate": self.total_row_estimate,
            "data_quality_warnings": self.data_quality_warnings,
            "table_coverage": self.table_coverage,
        }
