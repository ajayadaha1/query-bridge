"""Shared type aliases for QueryBridge."""

from typing import Any, Dict, List, Optional, Tuple

# Row from a query result
Row = Dict[str, Any]

# Column metadata
ColumnName = str
TableName = str

# Tool call ID
ToolCallId = str

# JSON-serializable dict
JsonDict = Dict[str, Any]
