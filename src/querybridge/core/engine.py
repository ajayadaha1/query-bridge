"""QueryBridgeEngine — Main orchestrator wiring all components together."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from querybridge.agent.loop import AgentLoop
from querybridge.core.config import EngineConfig
from querybridge.core.models import QueryRequest, QueryResponse
from querybridge.memory.persistent import PersistentQueryMemory
from querybridge.memory.exploration import ExplorationMemory
from querybridge.memory.store import MemoryStore
from querybridge.plugins.builtin.generic import GenericPlugin
from querybridge.plugins.registry import PluginRegistry
from querybridge.prompts.few_shot import FewShotRegistry
from querybridge.schema.cache import SchemaCache

if TYPE_CHECKING:
    from querybridge.connectors.base import DatabaseConnector
    from querybridge.llm.base import LLMProvider
    from querybridge.plugins.base import DomainPlugin

logger = logging.getLogger("querybridge.engine")


class QueryBridgeEngine:
    """Top-level NL2SQL engine.

    Usage::

        engine = QueryBridgeEngine(
            connector=PostgreSQLConnector(dsn),
            llm=OpenAIProvider(api_key=key),
        )
        response = await engine.query("How many users signed up last month?")
    """

    def __init__(
        self,
        connector: DatabaseConnector,
        llm: LLMProvider,
        config: EngineConfig | None = None,
        plugin: DomainPlugin | None = None,
        datasource_id: str = "default",
    ):
        self.connector = connector
        self.llm = llm
        self.config = config or EngineConfig()
        self.plugin = plugin or GenericPlugin()
        self.schema_cache = SchemaCache(
            connector, self.plugin, cache_dir="/tmp/querybridge_cache"
        )
        self.memory_store = MemoryStore(
            max_sessions=100, ttl_seconds=self.config.session_ttl_seconds
        )
        self.few_shot = FewShotRegistry()
        self.persistent_memory = PersistentQueryMemory(datasource=datasource_id)
        self.exploration_memory = ExplorationMemory(datasource=datasource_id)
        self.rag_sync = None  # Set by api.py for PostgreSQL datasources

        # Register plugin few-shot examples
        for ex in self.plugin.get_few_shot_examples():
            self.few_shot.add_example(
                question=ex["question"],
                sql=ex["sql"],
                explanation=ex.get("explanation", ""),
            )

        self._agent = AgentLoop(
            connector=self.connector,
            llm=self.llm,
            config=self.config,
            plugin=self.plugin,
            schema_cache=self.schema_cache,
            memory_store=self.memory_store,
            few_shot=self.few_shot,
            persistent_memory=self.persistent_memory,
            rag_sync=self.rag_sync,
            exploration_memory=self.exploration_memory,
        )

        logger.info(
            f"QueryBridgeEngine initialized: "
            f"connector={type(connector).__name__}, "
            f"llm={type(llm).__name__}, "
            f"plugin={self.plugin.get_name()}"
        )

    async def query(
        self,
        question: str,
        chat_id: str | None = None,
        history: list | None = None,
    ) -> QueryResponse:
        """Execute a natural language query."""
        request = QueryRequest(
            question=question,
            chat_id=chat_id,
            history=history or [],
        )
        return await self._agent.run(request)

    async def query_stream(
        self,
        question: str,
        chat_id: str | None = None,
        history: list | None = None,
    ):
        """Execute a query with streaming progress events (async generator)."""
        request = QueryRequest(
            question=question,
            chat_id=chat_id,
            history=history or [],
        )
        async for event in self._agent.run_streaming(request):
            yield event

    async def close(self):
        """Clean up resources."""
        await self.connector.close()
        if self.rag_sync:
            try:
                await self.rag_sync.close()
            except Exception:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    @classmethod
    def from_config(
        cls,
        connector: DatabaseConnector,
        llm: LLMProvider,
        config_dict: dict[str, Any] | None = None,
        plugin_name: str | None = None,
    ) -> QueryBridgeEngine:
        """Create an engine from a config dict and optional plugin name."""
        config = EngineConfig(**(config_dict or {}))

        plugin: DomainPlugin | None = None
        if plugin_name:
            registry = PluginRegistry()
            registry.discover_entry_points()
            plugin = registry.get(plugin_name)

        return cls(
            connector=connector,
            llm=llm,
            config=config,
            plugin=plugin,
        )
