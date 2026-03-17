"""CSV export."""

from __future__ import annotations

import csv
import io
from typing import Any


def to_csv(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Convert query results to CSV string."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    return output.getvalue()


def to_csv_bytes(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    """Convert query results to CSV bytes (for streaming responses)."""
    return to_csv(columns, rows).encode("utf-8")
