"""ResultValidator — Post-execution validation for query results.

Detects anomalies like zero rows, high NULL rates, JOIN explosions,
duplicate queries, and single-value columns.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ValidationNote:
    """A single validation finding."""
    severity: str      # "warning" | "error" | "info"
    code: str          # "zero_rows" | "suspect_few" | "too_many" | "high_null" | "duplicate" | "single_value"
    message: str
    suggestions: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    """Aggregated result of all validation checks."""
    notes: list[ValidationNote] = field(default_factory=list)
    is_valid: bool = True
    should_retry: bool = False

    def add_note(self, note: ValidationNote):
        self.notes.append(note)
        if note.severity == "error":
            self.is_valid = False
            self.should_retry = True
        elif note.severity == "warning":
            self.should_retry = True

    def has_issues(self) -> bool:
        return len(self.notes) > 0

    def get_summary(self) -> str:
        if not self.notes:
            return "All validation checks passed."
        lines = []
        for note in self.notes:
            lines.append(f"[{note.severity.upper()}] {note.code}: {note.message}")
            for suggestion in note.suggestions:
                lines.append(f"  -> {suggestion}")
        return "\n".join(lines)


class ResultValidator:
    """Validates SQL query results to detect anomalies."""

    NULL_RATE_THRESHOLD = 0.50
    SUSPICIOUSLY_FEW_RATIO = 0.10

    def __init__(
        self,
        expected_row_estimate: int | None = None,
        total_table_rows: int | None = None,
    ):
        self.executed_queries: list[str] = []
        self.executed_query_hashes: set = set()
        self.expected_row_estimate = expected_row_estimate
        self.total_table_rows = total_table_rows
        self.zero_row_events = 0

    def validate(self, tool_result: dict[str, Any], sql: str) -> ValidationResult:
        """Run all validation rules against a query result."""
        result = ValidationResult()

        if "error" in tool_result:
            result.add_note(ValidationNote(
                severity="error", code="execution_error",
                message=f"Query execution failed: {tool_result['error']}",
                suggestions=[
                    "Check SQL syntax for errors",
                    "Verify table and column names exist",
                    "Use explore_table to check available columns",
                ],
            ))
            return result

        for check in [
            self._check_duplicate(sql),
            self._check_zero_rows(tool_result),
            self._check_row_count(tool_result, sql),
            self._check_null_rate(tool_result),
            self._check_single_value(tool_result),
        ]:
            if check is not None:
                result.add_note(check)
                if check.code == "zero_rows":
                    self.zero_row_events += 1

        self._track_query(sql)
        return result

    def _check_zero_rows(self, result: dict[str, Any]) -> ValidationNote | None:
        if result.get("row_count", 0) == 0:
            return ValidationNote(
                severity="warning", code="zero_rows",
                message="Query returned 0 rows. This may indicate incorrect filter values.",
                suggestions=[
                    "Use get_distinct_values() to verify filter values",
                    "Consider case sensitivity: use ILIKE instead of =",
                    "Verify date ranges include the expected period",
                ],
            )
        return None

    def _check_row_count(self, result: dict[str, Any], sql: str = "") -> ValidationNote | None:
        row_count = result.get("row_count", 0)
        truncated = result.get("truncated", False)
        if row_count == 0:
            return None

        if self.total_table_rows and truncated and row_count >= self.total_table_rows:
            return ValidationNote(
                severity="error", code="too_many",
                message=(
                    f"Row count ({row_count}+) exceeds table size "
                    f"({self.total_table_rows}). Possible JOIN explosion."
                ),
                suggestions=["Add DISTINCT", "Check JOIN conditions", "Add GROUP BY"],
            )

        if self.expected_row_estimate and self.expected_row_estimate > 0:
            sql_upper = sql.upper()
            if "GROUP BY" in sql_upper or "LIMIT" in sql_upper:
                return None
            threshold = max(1, int(self.expected_row_estimate * self.SUSPICIOUSLY_FEW_RATIO))
            if row_count < threshold:
                return ValidationNote(
                    severity="warning", code="suspect_few",
                    message=f"Only {row_count} rows (expected ~{self.expected_row_estimate}).",
                    suggestions=["Verify filter values", "Check if WHERE is too restrictive"],
                )
        return None

    def _check_null_rate(self, result: dict[str, Any]) -> ValidationNote | None:
        rows = result.get("rows", [])
        columns = result.get("columns", [])
        row_count = result.get("row_count", 0)
        if row_count == 0 or not columns:
            return None

        high_null = []
        for col in columns:
            null_count = sum(1 for row in rows if row.get(col) is None)
            rate = null_count / row_count
            if rate > self.NULL_RATE_THRESHOLD:
                high_null.append((col, rate))

        if high_null:
            detail = ", ".join(f"{c} ({r*100:.0f}% NULL)" for c, r in high_null)
            return ValidationNote(
                severity="warning", code="high_null",
                message=f"High NULL rate: {detail}.",
                suggestions=["Verify column names", "Check if a JOIN is missing"],
            )
        return None

    def _check_duplicate(self, sql: str) -> ValidationNote | None:
        h = self._hash_query(sql)
        if h in self.executed_query_hashes:
            return ValidationNote(
                severity="warning", code="duplicate",
                message="This exact query was already executed.",
                suggestions=["Modify the query to address the previous issue"],
            )
        return None

    def _check_single_value(self, result: dict[str, Any]) -> ValidationNote | None:
        rows = result.get("rows", [])
        columns = result.get("columns", [])
        if result.get("row_count", 0) <= 1 or not columns:
            return None

        single = []
        for col in columns:
            non_null = [str(row.get(col)) for row in rows if row.get(col) is not None]
            if len(non_null) >= 2 and len(set(non_null)) == 1:
                single.append((col, non_null[0][:50]))

        if single:
            detail = ", ".join(f"{c}='{v}'" for c, v in single)
            return ValidationNote(
                severity="info", code="single_value",
                message=f"Identical values across all rows: {detail}.",
                suggestions=["Expected for columns used in WHERE clauses"],
            )
        return None

    def _hash_query(self, sql: str) -> str:
        return hashlib.md5(" ".join(sql.lower().split()).encode()).hexdigest()

    def _track_query(self, sql: str):
        self.executed_queries.append(sql)
        self.executed_query_hashes.add(self._hash_query(sql))

    def set_expectations(self, expected: int | None = None, total: int | None = None):
        if expected is not None:
            self.expected_row_estimate = expected
        if total is not None:
            self.total_table_rows = total

    def reset(self):
        self.executed_queries.clear()
        self.executed_query_hashes.clear()
        self.zero_row_events = 0
