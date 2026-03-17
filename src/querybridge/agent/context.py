"""ContextWindowManager — Prevents token budget explosion in the agentic loop.

Manages message history by:
- Tracking estimated token usage per message
- Compressing old tool results to summaries
- Keeping the last N tool results in full detail
- Never compressing: system message, user message
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger("querybridge.agent.context")


class ContextWindowManager:
    """Manages context window within the NL2SQL agentic loop."""

    MAX_TOKENS = 128_000
    TOKEN_BUDGET_FOR_HISTORY = 90_000
    CHARS_PER_TOKEN = 3.5
    MAX_HISTORY_CHARS = int(TOKEN_BUDGET_FOR_HISTORY * CHARS_PER_TOKEN)

    def __init__(
        self,
        max_context_chars: int = 120_000,
        keep_recent_results: int = 3,
    ):
        self.max_context_chars = max_context_chars
        self.keep_recent_results = keep_recent_results
        self.current_estimate = 0
        self.message_sizes: list[int] = []

    def estimate_message_size(self, message: dict) -> int:
        size = 0
        content = message.get("content", "")
        if isinstance(content, str):
            size += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict):
                    size += len(json.dumps(part, default=str))
                else:
                    size += len(str(part))
        for tc in message.get("tool_calls", []):
            if isinstance(tc, dict):
                size += len(json.dumps(tc, default=str))
            else:
                size += 200
        return size

    def track_message(self, message: dict):
        size = self.estimate_message_size(message)
        self.message_sizes.append(size)
        self.current_estimate += size

    def should_compress(self) -> bool:
        return self.current_estimate > self.max_context_chars * 0.7

    def compress_history(self, messages: list[dict]) -> list[dict]:
        """Replace old tool results with summaries, keeping last N in full."""
        if len(messages) <= 4:
            return messages

        compressed = []
        tool_result_indices = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "tool":
                tool_result_indices.append(i)

        keep_indices = set(tool_result_indices[-self.keep_recent_results:])

        for i, msg in enumerate(messages):
            role = msg.get("role", "")
            if role in ("system", "user", "assistant"):
                compressed.append(msg)
            elif role == "tool":
                if i in keep_indices:
                    compressed.append(msg)
                else:
                    compressed.append(self._summarize_tool_result(msg))
            else:
                compressed.append(msg)

        self.current_estimate = sum(self.estimate_message_size(m) for m in compressed)
        self.message_sizes = [self.estimate_message_size(m) for m in compressed]
        logger.debug(
            f"Context compressed: {len(messages)} -> {len(compressed)} messages, "
            f"~{self.current_estimate} chars"
        )
        return compressed

    def truncate_to_budget(self, messages: list[dict]) -> list[dict]:
        """Hard-truncate messages to fit model context window.

        Groups messages into atomic turns (assistant+tool_calls + tool responses)
        and drops oldest turns until within budget.
        """
        total_chars = sum(self.estimate_message_size(m) for m in messages)
        if total_chars <= self.MAX_HISTORY_CHARS:
            return messages

        logger.warning(
            f"Context budget exceeded: {total_chars:,} chars, "
            f"budget={self.MAX_HISTORY_CHARS:,} chars. Truncating."
        )

        # Group messages into atomic turns
        system_turns: list[list[dict]] = []
        conversation_turns: list[list[dict]] = []
        i = 0
        while i < len(messages):
            msg = messages[i]
            role = msg.get("role", "")

            if role == "system":
                system_turns.append([msg])
                i += 1
                continue

            if role == "assistant" and msg.get("tool_calls"):
                turn = [msg]
                j = i + 1
                while j < len(messages) and messages[j].get("role") == "tool":
                    turn.append(messages[j])
                    j += 1
                conversation_turns.append(turn)
                i = j
                continue

            conversation_turns.append([msg])
            i += 1

        # Separate last user turn
        last_user_turn = None
        if conversation_turns:
            last = conversation_turns[-1]
            if len(last) == 1 and last[0].get("role") == "user":
                last_user_turn = conversation_turns.pop()

        def turn_size(turn: list[dict]) -> int:
            return sum(self.estimate_message_size(m) for m in turn)

        fixed_chars = sum(turn_size(t) for t in system_turns)
        if last_user_turn:
            fixed_chars += turn_size(last_user_turn)

        history_budget = max(self.MAX_HISTORY_CHARS - fixed_chars, 20_000)

        # Keep turns from end, drop from start
        kept_turns: list[list[dict]] = []
        running_chars = 0
        for turn in reversed(conversation_turns):
            ts = turn_size(turn)
            if running_chars + ts > history_budget:
                break
            kept_turns.append(turn)
            running_chars += ts
        kept_turns.reverse()

        dropped = len(conversation_turns) - len(kept_turns)
        if dropped > 0:
            logger.info(f"Dropped {dropped} oldest turns to fit budget.")
            system_turns.append([{
                "role": "system",
                "content": (
                    f"[Note: {dropped} older conversation turns were trimmed "
                    f"to fit context window. Recent history is preserved below.]"
                ),
            }])

        result = []
        for t in system_turns:
            result.extend(t)
        for t in kept_turns:
            result.extend(t)
        if last_user_turn:
            result.extend(last_user_turn)

        self.current_estimate = sum(self.estimate_message_size(m) for m in result)
        self.message_sizes = [self.estimate_message_size(m) for m in result]
        return result

    def _summarize_tool_result(self, tool_msg: dict) -> dict:
        content = tool_msg.get("content", "")
        tool_call_id = tool_msg.get("tool_call_id", "")
        summary = self._extract_summary(content)
        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": f"[SUMMARIZED] {summary}",
        }

    def _extract_summary(self, content: str) -> str:
        if not content:
            return "Empty result"
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                parts = []
                if "row_count" in data:
                    parts.append(f"{data['row_count']} rows")
                if data.get("truncated"):
                    parts.append("truncated")
                if isinstance(data.get("columns"), list):
                    parts.append(f"{len(data['columns'])} columns")
                if "table" in data:
                    parts.append(f"table={data['table']}")
                if "error" in data:
                    parts.append(f"error: {str(data['error'])[:100]}")
                if "total_distinct" in data:
                    parts.append(f"{data['total_distinct']} distinct values")
                if "total_matches" in data:
                    parts.append(f"{data['total_matches']} matches")
                if parts:
                    return "; ".join(parts)
        except (json.JSONDecodeError, TypeError):
            pass
        if len(content) > 200:
            return content[:200] + "..."
        return content

    def get_phase_summary(self, messages: list[dict], phase_name: str) -> str:
        findings = []
        for msg in messages:
            if msg.get("role") == "tool":
                content = msg.get("content", "")
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if data.get("row_count", -1) == 0:
                            findings.append("Query returned 0 rows")
                        elif "row_count" in data:
                            findings.append(f"Found {data['row_count']} rows")
                        if "total_distinct" in data:
                            findings.append(
                                f"{data.get('column', '?')}: {data['total_distinct']} distinct values"
                            )
                except (json.JSONDecodeError, TypeError):
                    pass
        if not findings:
            return f"{phase_name} phase: no significant findings."
        return f"{phase_name} phase findings: " + "; ".join(findings[:5])

    def get_usage_report(self) -> dict:
        return {
            "estimated_chars": self.current_estimate,
            "estimated_tokens": self.current_estimate // 4,
            "max_chars": self.max_context_chars,
            "usage_pct": round(self.current_estimate / self.max_context_chars * 100, 1),
            "message_count": len(self.message_sizes),
            "should_compress": self.should_compress(),
        }

    def reset(self):
        self.current_estimate = 0
        self.message_sizes = []
