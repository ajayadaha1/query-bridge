"""JSON export."""

from __future__ import annotations

import json
from typing import Any


def to_json(
    columns: list[str],
    rows: list[dict[str, Any]],
    indent: int = 2,
    metadata: dict[str, Any] | None = None,
) -> str:
    """Convert query results to JSON string."""
    result: dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
    if metadata:
        result["metadata"] = metadata
    return json.dumps(result, indent=indent, default=str)
