"""LiteLLM provider — supports 100+ LLM providers."""

from __future__ import annotations

import json
import logging
from typing import Any

from querybridge.llm.base import LLMProvider, LLMResponse

logger = logging.getLogger("querybridge.llm.litellm")


class LiteLLMProvider(LLMProvider):
    """LiteLLM provider — wraps any LLM via litellm."""

    def __init__(self, model: str = "gpt-4o", **kwargs):
        import litellm  # noqa: F401
        self._model = model
        self._extra_kwargs = kwargs

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.0,
    ) -> LLMResponse:
        import litellm

        kwargs: dict[str, Any] = {
            "model": model or self._model,
            "messages": messages,
            "temperature": temperature,
            **self._extra_kwargs,
        }
        if tools:
            kwargs["tools"] = tools

        response = await litellm.acompletion(**kwargs)
        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = {"_raw": tc.function.arguments}
                tool_calls.append({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": json.dumps(args),
                    },
                })

        return LLMResponse(
            content=message.content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason or "stop",
        )
