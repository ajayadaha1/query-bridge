# QueryBridge

**Connect any database. Ask questions in plain English. Get accurate SQL-backed answers.**

QueryBridge is an agentic NL2SQL engine that auto-discovers your schema, translates natural language to SQL, executes safely, validates results, and returns structured answers with confidence scoring.

## Why QueryBridge?

| Feature | QueryBridge | Vanna.ai | LangChain SQL | Raw LLM |
|---|:---:|:---:|:---:|:---:|
| Agentic multi-step reasoning | ✅ | ❌ | ❌ | ❌ |
| Auto schema discovery | ✅ | Partial | ❌ | ❌ |
| SQL safety guard rails | ✅ | ❌ | Partial | ❌ |
| Result validation | ✅ | ❌ | ❌ | ❌ |
| Domain plugin system | ✅ | ❌ | ❌ | ❌ |
| Multi-database support | ✅ | ✅ | ✅ | ❌ |
| Conversation memory | ✅ | ❌ | ✅ | ❌ |
| Confidence scoring | ✅ | ❌ | ❌ | ❌ |

## Quick Start

```bash
pip install querybridge
```

```python
from querybridge import QueryBridgeEngine
from querybridge.connectors.sqlite import SQLiteConnector
from querybridge.llm.openai_provider import OpenAIProvider

engine = QueryBridgeEngine(
    connector=SQLiteConnector("my_database.db"),
    llm=OpenAIProvider(api_key="sk-..."),
)

response = await engine.query("How many users signed up last month?")
print(response.answer)
```

[Get Started →](getting-started/installation.md){ .md-button .md-button--primary }
[View on GitHub →](https://github.com/querybridge/querybridge){ .md-button }
