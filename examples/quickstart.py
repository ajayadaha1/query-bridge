"""QueryBridge Quickstart — Ask questions to a SQLite database in 10 lines."""

import asyncio
from querybridge import QueryBridgeEngine
from querybridge.connectors.sqlite import SQLiteConnector
from querybridge.llm.openai_provider import OpenAIProvider


async def main():
    async with QueryBridgeEngine(
        connector=SQLiteConnector("demo/chinook.db"),
        llm=OpenAIProvider(api_key="sk-..."),  # or set OPENAI_API_KEY env var
    ) as engine:
        response = await engine.query("What are the top 5 best-selling artists?")

        print(response.answer)
        print(f"\nSQL: {response.last_sql}")
        print(f"Confidence: {response.confidence_score}")
        print(f"Queries executed: {response.queries_executed}")


if __name__ == "__main__":
    asyncio.run(main())
