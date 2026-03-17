<div align="center">

# 🌉 QueryBridge

### Talk to your database. Get answers.

**The open-source NL2SQL engine that actually works in production.**

[![PyPI version](https://img.shields.io/pypi/v/querybridge?color=blue)](https://pypi.org/project/querybridge/)
[![CI](https://github.com/querybridge/querybridge/actions/workflows/ci.yml/badge.svg)](https://github.com/querybridge/querybridge/actions/workflows/ci.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Downloads](https://img.shields.io/pypi/dm/querybridge)](https://pypi.org/project/querybridge/)

[Documentation](https://github.com/ajayadaha1/query-bridge/tree/main/docs) · [Playground](https://failsafe.amd.com/query-bridge/) · [Issues](https://github.com/ajayadaha1/query-bridge/issues)

</div>

---

> **Ask questions in English. Get SQL + answers + confidence scores.** No prompt engineering required.
>
> QueryBridge uses an agentic loop that discovers your schema, classifies questions, generates SQL, validates results, and self-corrects — all in one call.

<br>

## 30-Second Demo

```bash
pip install querybridge[sqlite]
```

```python
import asyncio
from querybridge.core.engine import QueryBridgeEngine
from querybridge.connectors.sqlite import SQLiteConnector
from querybridge.llm.openai_provider import OpenAIProvider

async def main():
    async with QueryBridgeEngine(
        connector=SQLiteConnector("chinook.db"),
        llm=OpenAIProvider(api_key="sk-..."),
    ) as engine:
        result = await engine.query("What are the top 5 selling artists?")
        print(result.answer)          # "The top 5 artists by sales are..."
        print(result.last_sql)        # SELECT a.Name, SUM(...) ...
        print(result.confidence_score) # 0.95

asyncio.run(main())
```

**Or use Docker with the built-in playground:**

```bash
git clone https://github.com/querybridge/querybridge && cd querybridge
echo "OPENAI_API_KEY=sk-..." > .env
docker compose up
# Open http://localhost:3000 — start chatting with the demo database
```

<br>

## Why QueryBridge?

| | Raw LLM | LangChain SQL | **QueryBridge** |
|---|---|---|---|
| Self-correcting queries | ❌ | ❌ | ✅ Agentic loop retries |
| Schema discovery | ❌ | Partial | ✅ Auto-discovers everything |
| Safety (blocks DROP/DELETE) | ❌ | ❌ | ✅ SQL Guard + read-only |
| Confidence scoring | ❌ | ❌ | ✅ Per-query scores |
| Plugin system | ❌ | ❌ | ✅ Domain plugins |
| Conversation memory | ❌ | Manual | ✅ Built-in |
| MCP tool server | ❌ | ❌ | ✅ Works with any AI agent |
| Swap LLMs in one line | ❌ | Partial | ✅ OpenAI/Anthropic/100+ |

<br>

## Features

- **Any Database** — PostgreSQL, SQLite, MySQL, SQL Server, Snowflake, BigQuery (via SQLAlchemy)
- **Any LLM** — OpenAI, Anthropic, or 100+ models via LiteLLM
- **Agentic Loop** — Multi-step reasoning: classify → discover → generate → validate → self-correct
- **Safety First** — SQL Guard blocks destructive queries. Read-only connections. Result validation.
- **Plugin System** — Inject domain knowledge (e-commerce, healthcare, finance) without touching core code
- **5 Server Modes** — Python API, REST (FastAPI), WebSocket, CLI, MCP tool server
- **Schema Discovery** — Auto-discovers tables, columns, types, relationships, and enums
- **Conversation Memory** — Multi-turn context across questions in a session
- **Export** — CSV, JSON, Excel with one method call

<br>

## How It Works

```
User Question
     │
     ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  Classifier  │────▶│   Discovery   │────▶│  SQL Guard   │
│ (question    │     │ (schema +     │     │ (block       │
│  type/intent)│     │  entity match)│     │  dangerous)  │
└─────────────┘     └──────────────┘     └──────┬──────┘
                                                 │
     ┌───────────────────────────────────────────┘
     ▼
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  LLM Agent   │────▶│   Execute     │────▶│  Validator   │
│ (generate    │◀───│ (run query    │     │ (check       │
│  SQL + tools)│ ↻  │  read-only)   │     │  results)    │
└─────────────┘     └──────────────┘     └──────┬──────┘
  self-correct                                   │
  loop (max 5)                                   ▼
                                          Final Answer
                                        + SQL + Confidence
```

<br>

## Installation

```bash
# Core only
pip install querybridge

# With database drivers
pip install "querybridge[postgresql]"    # asyncpg
pip install "querybridge[sqlite]"        # aiosqlite
pip install "querybridge[all]"           # everything

# From source
git clone https://github.com/querybridge/querybridge
cd querybridge
make dev
```

<br>

## Usage

### CLI

```bash
# Ask a question
querybridge query "How many customers are in each country?" \
  --dsn "postgresql://user:pass@localhost/mydb" \
  --api-key "sk-..."

# Start the REST API
querybridge serve --port 8000

# Interactive REPL with conversation memory
querybridge interactive

# MCP tool server (for Claude, Cursor, etc.)
querybridge mcp
```

### REST API

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question": "What are the top 10 products by revenue?"}'
```

```json
{
  "answer": "The top 10 products by revenue are...",
  "sql": "SELECT p.name, SUM(ii.unit_price * ii.quantity) AS revenue FROM ...",
  "confidence_score": 0.92,
  "row_count": 10,
  "execution_time_ms": 340
}
```

### Domain Plugins

Inject expert knowledge for your specific database:

```python
from querybridge.plugins.base import DomainPlugin

class HealthcarePlugin(DomainPlugin):
    def get_name(self) -> str:
        return "healthcare"

    def get_column_annotations(self):
        return {
            "patients.mrn": "Medical Record Number — unique patient identifier",
            "encounters.type": "Values: inpatient, outpatient, emergency, observation",
        }

    def get_few_shot_examples(self):
        return [{
            "question": "How many patients were readmitted within 30 days?",
            "sql": "SELECT COUNT(DISTINCT p.id) FROM patients p ...",
        }]
```

```toml
# pyproject.toml — auto-discovered via entry points
[project.entry-points."querybridge.plugins"]
healthcare = "my_package:HealthcarePlugin"
```

<br>

## Configuration

| Env Variable | Description | Default |
|---|---|---|
| `QUERYBRIDGE_DSN` | Database connection string | — |
| `QUERYBRIDGE_API_KEY` | LLM API key | — |
| `QUERYBRIDGE_MODEL` | LLM model name | `gpt-4o` |
| `QUERYBRIDGE_PROVIDER` | LLM provider (`openai` / `anthropic` / `litellm`) | `openai` |
| `QUERYBRIDGE_BASE_URL` | Custom API base URL (for local/proxy LLMs) | — |

<br>

## Project Structure

```
querybridge/
├── src/querybridge/
│   ├── core/           # Engine orchestrator, config, models
│   ├── connectors/     # PostgreSQL, SQLite, Generic (SQLAlchemy)
│   ├── llm/            # OpenAI, Anthropic, LiteLLM providers
│   ├── safety/         # SQL Guard, Validator, Sanitizer
│   ├── schema/         # Discovery, caching, relationship detection
│   ├── classifier/     # Question classification, entity extraction
│   ├── discovery/      # Pre-flight filter verification, fuzzy match
│   ├── strategy/       # Query strategy tracking, column hierarchy
│   ├── memory/         # Conversation memory, session store
│   ├── prompts/        # System prompts, few-shot registry
│   ├── plugins/        # Plugin ABC, registry, builtins
│   ├── agent/          # Agentic loop, tool registry, context manager
│   ├── server/         # REST API, WebSocket, MCP, CLI
│   └── export/         # CSV, JSON, Excel
├── playground/         # Zero-dependency chat UI
├── demo/               # Chinook demo database
├── examples/           # Example scripts
├── tests/              # Test suite
└── docs/               # MkDocs documentation
```

<br>

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for details.

```bash
make dev          # Install with dev dependencies
make test         # Run tests
make lint         # Run linter
make format       # Auto-format code
make docker-up    # Start with Docker
```

<br>

## License

MIT — use it anywhere.

---

<div align="center">

**Built with** 🐍 Python · ⚡ asyncio · 🤖 LLMs

[Star this repo](https://github.com/querybridge/querybridge) if you find it useful!

</div>
