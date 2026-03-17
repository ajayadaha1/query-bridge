"""Use QueryBridge with different LLM providers."""

import asyncio
from querybridge import QueryBridgeEngine
from querybridge.connectors.sqlite import SQLiteConnector

# ─── OpenAI ──────────────────────────────────────────────────────────
from querybridge.llm.openai_provider import OpenAIProvider

openai_engine = QueryBridgeEngine(
    connector=SQLiteConnector("demo/chinook.db"),
    llm=OpenAIProvider(api_key="sk-...", model="gpt-4o"),
)

# ─── Anthropic ───────────────────────────────────────────────────────
from querybridge.llm.anthropic_provider import AnthropicProvider

anthropic_engine = QueryBridgeEngine(
    connector=SQLiteConnector("demo/chinook.db"),
    llm=AnthropicProvider(api_key="sk-ant-...", model="claude-sonnet-4-20250514"),
)

# ─── LiteLLM (100+ models: Ollama, Azure, Bedrock, etc.) ────────────
from querybridge.llm.litellm_provider import LiteLLMProvider

# Local Ollama
ollama_engine = QueryBridgeEngine(
    connector=SQLiteConnector("demo/chinook.db"),
    llm=LiteLLMProvider(model="ollama/llama3"),
)

# Azure OpenAI
azure_engine = QueryBridgeEngine(
    connector=SQLiteConnector("demo/chinook.db"),
    llm=LiteLLMProvider(model="azure/gpt-4o", api_key="..."),
)

# ─── Custom base URL (e.g., corporate proxy) ────────────────────────
proxy_engine = QueryBridgeEngine(
    connector=SQLiteConnector("demo/chinook.db"),
    llm=OpenAIProvider(
        api_key="your-key",
        model="gpt-4o",
        base_url="https://your-proxy.company.com/v1",
    ),
)


async def main():
    async with openai_engine:
        response = await openai_engine.query("How many tracks are there?")
        print(response.answer)


if __name__ == "__main__":
    asyncio.run(main())
