"""Input sanitization — defense against prompt injection and SQL injection."""

import re


def sanitize_user_input(text: str, max_length: int = 2000) -> str:
    """Sanitize user input for safe processing.

    Applies basic input hygiene:
    - Truncates to max_length to prevent context overflow
    - Removes null bytes

    Note: Prompt injection defense is handled by the system prompt
    design and tool-level validation, not by input stripping.
    """
    if not text:
        return ""

    # Truncate to max length
    text = text[:max_length].strip()

    # Remove null bytes
    text = text.replace("\x00", "")

    return text


def sanitize_sql_value(value: str) -> str:
    """Escape a string value for safe use in SQL.

    Uses parameterized queries where possible, but this is
    a fallback for dynamic value injection.
    """
    if not value:
        return ""
    return value.replace("'", "''")


def is_safe_identifier(name: str) -> bool:
    """Check if a string is a safe SQL identifier."""
    return bool(re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", name))
