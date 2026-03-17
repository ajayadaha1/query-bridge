"""Shared type aliases for QueryBridge."""

from typing import Any

# Row from a query result
Row = dict[str, Any]

# Column metadata
ColumnName = str
TableName = str

# Tool call ID
ToolCallId = str

# JSON-serializable dict
JsonDict = dict[str, Any]
