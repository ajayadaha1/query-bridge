"""ConversationMemory — Per-session in-memory store."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


DEFAULT_TTL_SECONDS = 1800


@dataclass
class ConversationMemory:
    """Per-chat-session memory of discovered values and patterns."""
    chat_id: str
    created_at: float = field(default_factory=time.time)
    last_accessed: float = field(default_factory=time.time)
    ttl_seconds: float = DEFAULT_TTL_SECONDS

    discovered_columns: Dict[str, List[str]] = field(default_factory=dict)
    verified_filters: Dict[str, int] = field(default_factory=dict)
    column_null_rates: Dict[str, float] = field(default_factory=dict)
    successful_patterns: List[Dict[str, str]] = field(default_factory=list)
    failed_patterns: List[Dict[str, str]] = field(default_factory=list)
    table_row_count: Optional[int] = None

    def is_expired(self) -> bool:
        return (time.time() - self.last_accessed) > self.ttl_seconds

    def touch(self):
        self.last_accessed = time.time()

    def add_discovered_column(self, column: str, values: List[str]):
        self.discovered_columns[column] = values
        self.touch()

    def add_verified_filter(self, filter_key: str, row_count: int):
        self.verified_filters[filter_key] = row_count
        self.touch()

    def add_null_rate(self, column: str, null_rate: float):
        self.column_null_rates[column] = null_rate
        self.touch()

    def add_successful_pattern(self, question_type: str, approach: str, sql: str = ""):
        self.successful_patterns.append({
            "question_type": question_type,
            "approach": approach,
            "sql": sql[:200] if sql else "",
        })
        self.touch()

    def add_failed_pattern(self, approach: str, reason: str):
        self.failed_patterns.append({"approach": approach, "reason": reason})
        self.touch()

    def format_for_prompt(self) -> str:
        """Format memory for system prompt injection."""
        if not self.discovered_columns and not self.verified_filters and not self.successful_patterns:
            return ""

        lines = ["## Conversation Memory (from previous turns)"]
        if self.verified_filters:
            lines.append("Verified filters:")
            for fk, count in list(self.verified_filters.items())[:10]:
                lines.append(f"  - {fk}: {count} rows")

        if self.column_null_rates:
            high = {k: v for k, v in self.column_null_rates.items() if v > 0.5}
            if high:
                lines.append("High NULL rate columns:")
                for col, rate in list(high.items())[:5]:
                    lines.append(f"  - {col}: {rate*100:.0f}% NULL")

        if self.successful_patterns:
            lines.append("Previous successful approaches:")
            for p in self.successful_patterns[-3:]:
                lines.append(f"  - [{p['question_type']}] {p['approach']}")

        if self.failed_patterns:
            lines.append("Approaches that failed (do NOT repeat):")
            for p in self.failed_patterns[-3:]:
                lines.append(f"  - {p['approach']}: {p['reason']}")

        return "\n".join(lines)
