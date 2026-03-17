"""JSON export."""

from __future__ import annotations

import json
from typing import Any, Dict, List


def to_json(
    columns: List[str],
    rows: List[Dict[str, Any]],
    indent: int = 2,
    metadata: Dict[str, Any] | None = None,
) -> str:
    """Convert query results to JSON string."""
    result: Dict[str, Any] = {
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }
    if metadata:
        result["metadata"] = metadata
    return json.dumps(result, indent=indent, default=str)
