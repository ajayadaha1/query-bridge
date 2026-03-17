# Architecture Overview

QueryBridge is organized as a layered, plugin-extensible system.

## Data Flow

```
User Question
  → QuestionClassifier (regex entity extraction, type detection)
  → DiscoveryEngine (verify entities against live DB values)
  → Build System Prompt (schema + discovery + memory + strategy)
  → AgentLoop (up to 15 iterations)
      → LLM generates tool calls
      → Dispatch: explore_table, get_distinct_values, execute_sql, ...
      → SQLGuard validates → Connector executes → ResultValidator checks
      → ContextWindowManager compresses if needed
  → QueryResponse (answer, SQL log, confidence, thinking steps)
```

## Package Structure

```
src/querybridge/
├── core/           # Config, models, engine orchestrator
├── connectors/     # Database adapters (PostgreSQL, SQLite, Generic)
├── llm/            # LLM providers (OpenAI, Anthropic, LiteLLM)
├── safety/         # SQLGuard, ResultValidator, Sanitizer
├── schema/         # Schema discovery, caching, relationship detection
├── classifier/     # Question classification, entity extraction
├── discovery/      # Pre-flight filter verification
├── strategy/       # Query strategy tracking, escalation
├── memory/         # Conversation memory, session management
├── prompts/        # System prompt building, few-shot examples
├── plugins/        # Domain plugin system
├── agent/          # Agentic loop, tool registry, context management
├── server/         # API, CLI, WebSocket, MCP server modes
└── export/         # CSV, JSON, Excel export
```

## Extension Points

| Component | Extension Mechanism |
|---|---|
| Databases | `DatabaseConnector` ABC |
| LLM Providers | `LLMProvider` ABC |
| Domain Knowledge | `DomainPlugin` ABC |
| Tools | `ToolRegistry.register()` |
| Export Formats | Add to `export/` module |
