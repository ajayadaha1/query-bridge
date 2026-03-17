"""Excel export (requires openpyxl or pandas)."""

from __future__ import annotations

import io
from typing import Any, Dict, List


def to_excel_bytes(columns: List[str], rows: List[Dict[str, Any]]) -> bytes:
    """Convert query results to Excel bytes.

    Requires pandas and openpyxl.
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError(
            "pandas is required for Excel export. "
            "Install with: pip install querybridge[export]"
        )

    df = pd.DataFrame(rows, columns=columns)
    buffer = io.BytesIO()
    df.to_excel(buffer, index=False, engine="openpyxl")
    return buffer.getvalue()
