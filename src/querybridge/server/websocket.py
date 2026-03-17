"""WebSocket server — streaming query responses."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from querybridge.core.engine import QueryBridgeEngine

logger = logging.getLogger("querybridge.server.websocket")


async def websocket_handler(websocket: Any, engine: QueryBridgeEngine):
    """Handle a WebSocket connection for streaming NL2SQL queries.

    Protocol:
    - Client sends: {"message": "...", "chat_id": "...", "history": [...]}
    - Server streams:
      - {"type": "thinking", "content": "..."}
      - {"type": "query_start", "sql": "...", "iteration": N}
      - {"type": "query_result", "row_count": N, "execution_time_ms": N}
      - {"type": "answer_chunk", "content": "..."}
      - {"type": "done", "chat_id": "...", "queries_executed": N, "confidence": 0.95}
    """
    try:
        from fastapi import WebSocket, WebSocketDisconnect
    except ImportError:
        raise ImportError("FastAPI is required for WebSocket mode.")

    try:
        await websocket.accept()

        while True:
            try:
                data = await websocket.receive_json()
            except Exception:
                break

            message = data.get("message", "")
            chat_id = data.get("chat_id")
            history = data.get("history", [])

            if not message:
                await websocket.send_json({"type": "error", "content": "Empty message"})
                continue

            # Run the query
            response = await engine.query(
                question=message,
                chat_id=chat_id,
                history=history,
            )

            # Stream thinking steps
            for step in response.thinking_steps:
                await websocket.send_json({
                    "type": "thinking",
                    "content": step.get("reasoning", ""),
                    "phase": step.get("phase", ""),
                    "iteration": step.get("iteration", 0),
                })

            # Stream answer
            await websocket.send_json({
                "type": "answer",
                "content": response.answer,
            })

            # Stream done
            await websocket.send_json({
                "type": "done",
                "chat_id": response.chat_id,
                "queries_executed": response.queries_executed,
                "confidence": response.confidence_score,
                "total_time_ms": response.total_time_ms,
                "last_sql": response.last_sql,
                "validation_notes": response.validation_notes,
            })

    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        try:
            await websocket.close()
        except Exception:
            pass
