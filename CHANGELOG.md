# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-01-01

### Added
- Core NL2SQL engine with agentic loop architecture
- Database connectors: PostgreSQL (asyncpg), SQLite (aiosqlite), Generic (SQLAlchemy)
- LLM providers: OpenAI, Anthropic, LiteLLM (100+ models)
- SQL safety system: guard, validator, sanitizer
- Schema discovery with caching and relationship detection
- Question classifier and entity extraction
- Discovery engine with fuzzy matching
- Strategy tracker and column hierarchy
- Conversation memory with session management
- Prompt system with few-shot registry
- Plugin system with entry-point discovery
- Server modes: REST API (FastAPI), WebSocket, MCP (stdio), CLI
- Export: CSV, JSON, Excel
- Playground chat UI
- Demo Chinook database (SQLite + PostgreSQL)
- Docker support with docker-compose
- MkDocs documentation site
- GitHub Actions CI/CD (test matrix, release, docs deploy)

[0.1.0]: https://github.com/querybridge/querybridge/releases/tag/v0.1.0
