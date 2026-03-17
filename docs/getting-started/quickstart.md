# Quickstart

Get answers from your database in under 5 minutes.

## 1. Install

```bash
pip install querybridge[sqlite]
```

## 2. Connect & Ask

```python
import asyncio
from querybridge import QueryBridgeEngine
from querybridge.connectors.sqlite import SQLiteConnector
from querybridge.llm.openai_provider import OpenAIProvider

async def main():
    async with QueryBridgeEngine(
        connector=SQLiteConnector("your_database.db"),
        llm=OpenAIProvider(api_key="sk-..."),
    ) as engine:
        response = await engine.query("How many records are in the database?")
        print(response.answer)
        print(f"SQL: {response.last_sql}")

asyncio.run(main())
```

## 3. What happens under the hood

When you call `engine.query()`, QueryBridge:

1. **Classifies** your question (count, trend, comparison, drill-down, etc.)
2. **Discovers** relevant entities and verifies filter values against the live database
3. **Builds** a context-rich prompt with schema info, discovery results, and domain knowledge
4. **Runs an agentic loop** where the LLM can:
    - Explore table structures
    - Check distinct column values
    - Execute SQL queries
    - Validate results
    - Cross-check from different angles
5. **Returns** a structured response with the answer, SQL, confidence score, and validation notes

## Next Steps

- [Docker Demo](docker.md) — Try the playground UI
- [Custom Plugins](../plugins/writing-plugins.md) — Add domain knowledge
- [Architecture](../architecture/overview.md) — Understand the internals
