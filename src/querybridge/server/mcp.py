"""MCP (Model Context Protocol) server mode for QueryBridge."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from querybridge.core.engine import QueryBridgeEngine

logger = logging.getLogger("querybridge.server.mcp")


class MCPServer:
    """QueryBridge as an MCP tool server.

    Exposes the NL2SQL engine as MCP-compatible tools that can be
    consumed by AI agents (e.g., Claude, Copilot).

    Tools exposed:
    - querybridge_ask: Ask a natural language question about the database
    - querybridge_sql: Execute a raw SQL query (read-only)
    - querybridge_schema: Get database schema information
    """

    def __init__(self, engine: QueryBridgeEngine):
        self.engine = engine

    def get_tool_definitions(self) -> list[dict[str, Any]]:
        """Return MCP tool definitions."""
        return [
            {
                "name": "querybridge_ask",
                "description": (
                    "Ask a natural language question about a database. "
                    "QueryBridge will translate it to SQL, execute it, and "
                    "return the answer with confidence scoring."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Natural language question about the data.",
                        },
                        "chat_id": {
                            "type": "string",
                            "description": "Optional session ID for conversation continuity.",
                        },
                    },
                    "required": ["question"],
                },
            },
            {
                "name": "querybridge_schema",
                "description": "Get the database schema information.",
                "inputSchema": {
                    "type": "object",
                    "properties": {},
                },
            },
        ]

    async def handle_tool_call(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Handle an MCP tool call."""
        if tool_name == "querybridge_ask":
            question = arguments.get("question", "")
            chat_id = arguments.get("chat_id")
            response = await self.engine.query(question=question, chat_id=chat_id)
            return {
                "content": [
                    {
                        "type": "text",
                        "text": response.answer,
                    }
                ],
                "metadata": {
                    "success": response.success,
                    "confidence": response.confidence_score,
                    "queries_executed": response.queries_executed,
                    "total_time_ms": response.total_time_ms,
                    "last_sql": response.last_sql,
                    "validation_notes": response.validation_notes,
                },
            }

        elif tool_name == "querybridge_schema":
            schema_text = await self.engine.schema_cache.get_schema_text()
            return {
                "content": [
                    {
                        "type": "text",
                        "text": schema_text,
                    }
                ],
            }

        else:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Unknown tool: {tool_name}",
                    }
                ],
                "isError": True,
            }

    async def run_stdio(self):
        """Run as an MCP server over stdio (for integration with AI agents)."""
        import sys

        logger.info("Starting QueryBridge MCP server (stdio mode)")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                method = request.get("method", "")

                if method == "tools/list":
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": {"tools": self.get_tool_definitions()},
                    }

                elif method == "tools/call":
                    params = request.get("params", {})
                    tool_name = params.get("name", "")
                    arguments = params.get("arguments", {})
                    result = await self.handle_tool_call(tool_name, arguments)
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "result": result,
                    }

                else:
                    response = {
                        "jsonrpc": "2.0",
                        "id": request.get("id"),
                        "error": {
                            "code": -32601,
                            "message": f"Method not found: {method}",
                        },
                    }

                print(json.dumps(response), flush=True)

            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON: {line[:100]}")
            except Exception as e:
                logger.error(f"MCP error: {e}")
                error_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32603, "message": str(e)},
                }
                print(json.dumps(error_resp), flush=True)
