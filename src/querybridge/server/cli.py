"""CLI entry point for QueryBridge."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Optional


def _build_engine(args):
    """Build a QueryBridgeEngine from CLI arguments."""
    from querybridge.core.config import EngineConfig
    from querybridge.core.engine import QueryBridgeEngine
    from querybridge.plugins.registry import PluginRegistry

    # Determine connector
    dsn = args.dsn or os.getenv("QUERYBRIDGE_DSN", "")
    if not dsn:
        print("Error: --dsn or QUERYBRIDGE_DSN environment variable is required.", file=sys.stderr)
        sys.exit(1)

    if dsn.startswith("postgresql://") or dsn.startswith("postgres://"):
        from querybridge.connectors.postgresql import PostgreSQLConnector
        connector = PostgreSQLConnector(dsn)
    elif dsn.endswith(".db") or dsn.endswith(".sqlite") or dsn.startswith("sqlite"):
        from querybridge.connectors.sqlite import SQLiteConnector
        path = dsn.replace("sqlite:///", "").replace("sqlite://", "")
        connector = SQLiteConnector(path)
    else:
        from querybridge.connectors.generic_sqlalchemy import GenericSQLAlchemyConnector
        connector = GenericSQLAlchemyConnector(dsn)

    # Determine LLM provider
    api_key = args.api_key or os.getenv("QUERYBRIDGE_API_KEY", os.getenv("OPENAI_API_KEY", ""))
    model = args.model or os.getenv("QUERYBRIDGE_MODEL", "gpt-4o")
    provider = args.provider or os.getenv("QUERYBRIDGE_PROVIDER", "openai")
    base_url = args.base_url or os.getenv("QUERYBRIDGE_BASE_URL")

    if provider == "anthropic":
        from querybridge.llm.anthropic_provider import AnthropicProvider
        llm = AnthropicProvider(api_key=api_key, model=model)
    elif provider == "litellm":
        from querybridge.llm.litellm_provider import LiteLLMProvider
        llm = LiteLLMProvider(model=model, api_key=api_key)
    else:
        from querybridge.llm.openai_provider import OpenAIProvider
        llm = OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    # Config
    config = EngineConfig(
        max_iterations=args.max_iterations,
        model=model,
    )

    # Plugin
    plugin = None
    if args.plugin:
        registry = PluginRegistry()
        registry.discover_entry_points()
        plugin = registry.get(args.plugin)
        if not plugin:
            print(f"Warning: Plugin '{args.plugin}' not found. Using generic.", file=sys.stderr)

    return QueryBridgeEngine(
        connector=connector,
        llm=llm,
        config=config,
        plugin=plugin,
    )


def cmd_query(args):
    """Handle the 'query' subcommand."""
    engine = _build_engine(args)

    async def _run():
        async with engine:
            response = await engine.query(args.question)
            if args.json:
                print(json.dumps({
                    "success": response.success,
                    "answer": response.answer,
                    "queries_executed": response.queries_executed,
                    "confidence": response.confidence_score,
                    "total_time_ms": response.total_time_ms,
                    "last_sql": response.last_sql,
                    "validation_notes": response.validation_notes,
                }, indent=2))
            else:
                print(response.answer)
                if response.last_sql:
                    print(f"\n--- SQL ---\n{response.last_sql}")
                if response.validation_notes:
                    print(f"\n--- Validation ---")
                    for note in response.validation_notes:
                        print(f"  • {note}")
                print(f"\n[{response.queries_executed} queries, "
                      f"{response.total_time_ms}ms, "
                      f"confidence: {response.confidence_score}]")

    asyncio.run(_run())


def cmd_serve(args):
    """Handle the 'serve' subcommand."""
    engine = _build_engine(args)

    from querybridge.server.api import create_app

    app = create_app(engine)

    try:
        import uvicorn
    except ImportError:
        print("Error: uvicorn is required. Install with: pip install querybridge[server]", file=sys.stderr)
        sys.exit(1)

    uvicorn.run(app, host=args.host, port=args.port)


def cmd_mcp(args):
    """Handle the 'mcp' subcommand."""
    engine = _build_engine(args)

    from querybridge.server.mcp import MCPServer

    server = MCPServer(engine)
    asyncio.run(server.run_stdio())


def cmd_interactive(args):
    """Handle the 'interactive' subcommand (REPL mode)."""
    engine = _build_engine(args)

    async def _run():
        async with engine:
            print("QueryBridge Interactive Mode")
            print("Type your questions. 'quit' or Ctrl+D to exit.\n")
            chat_id = None
            while True:
                try:
                    question = input("❯ ").strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nGoodbye!")
                    break

                if not question or question.lower() in ("quit", "exit", "q"):
                    break

                response = await engine.query(
                    question=question, chat_id=chat_id
                )
                chat_id = response.chat_id
                print(f"\n{response.answer}\n")
                print(f"  [{response.queries_executed} queries, "
                      f"{response.total_time_ms}ms, "
                      f"confidence: {response.confidence_score}]\n")

    asyncio.run(_run())


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="querybridge",
        description="QueryBridge — Natural Language to SQL",
    )
    parser.add_argument("--dsn", help="Database connection string")
    parser.add_argument("--api-key", help="LLM API key")
    parser.add_argument("--model", default="gpt-4o", help="LLM model name")
    parser.add_argument("--provider", default="openai", choices=["openai", "anthropic", "litellm"])
    parser.add_argument("--base-url", help="LLM API base URL")
    parser.add_argument("--plugin", help="Domain plugin name")
    parser.add_argument("--max-iterations", type=int, default=15)
    parser.add_argument("-v", "--verbose", action="store_true")

    subparsers = parser.add_subparsers(dest="command")

    # query subcommand
    query_parser = subparsers.add_parser("query", help="Ask a single question")
    query_parser.add_argument("question", help="Natural language question")
    query_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # serve subcommand
    serve_parser = subparsers.add_parser("serve", help="Start API server")
    serve_parser.add_argument("--host", default="0.0.0.0")
    serve_parser.add_argument("--port", type=int, default=8000)

    # mcp subcommand
    subparsers.add_parser("mcp", help="Start as MCP tool server (stdio)")

    # interactive subcommand
    subparsers.add_parser("interactive", help="Interactive REPL mode")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if args.command == "query":
        cmd_query(args)
    elif args.command == "serve":
        cmd_serve(args)
    elif args.command == "mcp":
        cmd_mcp(args)
    elif args.command == "interactive":
        cmd_interactive(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
