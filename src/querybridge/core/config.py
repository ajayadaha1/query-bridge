"""Engine configuration."""

from dataclasses import dataclass


@dataclass
class EngineConfig:
    """All tunable engine parameters."""

    # Agent behavior
    max_iterations: int = 15
    max_rows: int = 500
    statement_timeout_ms: int = 10_000
    max_query_length: int = 10_000
    temperature: float = 0.0

    # Context window
    max_context_chars: int = 120_000
    max_history_chars: int = 315_000

    # Schema discovery
    schema_cache_ttl_seconds: int = 300
    auto_discover: bool = True

    # Conversation memory
    session_ttl_seconds: int = 1800
    max_sessions: int = 100

    # Discovery
    fuzzy_match_threshold: float = 0.5

    # Safety
    blocked_keywords: set[str] | None = None
    blocked_patterns: list[str] | None = None

    # LLM
    model: str = "gpt-4o"
    temperature: float = 0.0
