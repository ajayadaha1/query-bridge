"""SQLGuard — Dialect-aware SQL validator for QueryBridge.

Defense-in-depth: validates that AI-generated SQL is safe before execution.
Works on top of the read-only DB role/connection.
"""

import re

# Universal blocked keywords (all dialects)
UNIVERSAL_BLOCKED = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT",
    "DROP", "ALTER", "TRUNCATE", "CREATE", "RENAME",
    "GRANT", "REVOKE",
    "COPY", "EXECUTE", "CALL", "DO",
    "SET", "RESET", "VACUUM", "ANALYZE", "REINDEX",
    "CLUSTER", "COMMENT", "SECURITY", "OWNER",
    "NOTIFY", "LISTEN", "UNLISTEN",
    "LOAD", "IMPORT", "EXPORT",
}

UNIVERSAL_PATTERNS = [
    r";\s*\w",                           # Multiple statements
    r"\bINTO\s+\w",                      # SELECT INTO / INSERT INTO
    r"\bCOPY\s+\w",                      # COPY command
    r"\\",                               # psql meta-commands
    r"\bEXPLAIN\s+ANALYZE\b",           # EXPLAIN ANALYZE actually executes
]

# Dialect-specific blocked keywords
DIALECT_BLOCKED = {
    "postgresql": {
        "PG_READ_FILE", "PG_READ_BINARY_FILE", "PG_LS_DIR", "PG_STAT_FILE",
        "LO_IMPORT", "LO_EXPORT", "LO_CREATE", "LO_UNLINK",
        "PG_CATALOG", "PG_SLEEP", "DBLINK",
    },
    "snowflake": {"PUT", "GET", "REMOVE", "STAGE"},
    "mysql": {"LOAD", "OUTFILE", "DUMPFILE", "HANDLER"},
    "sqlite": set(),
    "generic": set(),
}

DIALECT_PATTERNS = {
    "postgresql": [
        r"\bpg_sleep\b",
        r"\bgenerate_series\s*\([^)]*\d{6,}",
        r"\bdblink\b",
        r"\bcrosstab\b",
    ],
    "snowflake": [r"\bCOPY\s+INTO\b"],
    "mysql": [r"\bLOAD\s+DATA\b"],
    "sqlite": [],
    "generic": [],
}


class SQLGuard:
    """Validates SQL statements before execution. Dialect-aware."""

    DEFAULT_MAX_QUERY_LENGTH = 10_000

    def __init__(
        self,
        dialect: str = "generic",
        max_query_length: int = DEFAULT_MAX_QUERY_LENGTH,
        extra_blocked_keywords: set[str] | None = None,
        extra_blocked_patterns: list[str] | None = None,
    ):
        self.dialect = dialect
        self.max_query_length = max_query_length

        self.blocked_keywords = set(UNIVERSAL_BLOCKED)
        self.blocked_keywords.update(DIALECT_BLOCKED.get(dialect, set()))
        if extra_blocked_keywords:
            self.blocked_keywords.update(extra_blocked_keywords)

        self.blocked_patterns = list(UNIVERSAL_PATTERNS)
        self.blocked_patterns.extend(DIALECT_PATTERNS.get(dialect, []))
        if extra_blocked_patterns:
            self.blocked_patterns.extend(extra_blocked_patterns)

    def validate(self, sql: str) -> tuple[bool, str]:
        """
        Validate a SQL statement for safety.

        Returns:
            (is_safe, reason) — True/"OK" if safe, False/reason if blocked.
        """
        if not sql or not sql.strip():
            return False, "Empty SQL statement"

        sql_stripped = sql.strip()

        if len(sql_stripped) > self.max_query_length:
            return False, f"Query too long ({len(sql_stripped)} chars, max {self.max_query_length})"

        normalized = sql_stripped.upper()

        if not normalized.startswith(("SELECT", "WITH", "EXPLAIN")):
            return False, "Only SELECT/WITH/EXPLAIN queries allowed"

        if re.match(r"\s*EXPLAIN\s+ANALYZE\b", normalized):
            return False, "EXPLAIN ANALYZE not allowed (it executes the query)"

        tokens = set(re.findall(r"\b[A-Z_]+\b", normalized))
        violations = tokens & self.blocked_keywords
        if violations:
            return False, f"Blocked keywords found: {violations}"

        for pattern in self.blocked_patterns:
            if re.search(pattern, normalized, re.IGNORECASE):
                return False, f"Blocked pattern detected: {pattern}"

        statements = [s.strip() for s in sql_stripped.split(";") if s.strip()]
        if len(statements) > 1:
            return False, "Multiple SQL statements not allowed"

        return True, "OK"
