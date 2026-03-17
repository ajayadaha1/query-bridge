"""QueryBridgeEngine — Main orchestrator wiring all components together."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from querybridge.agent.loop import AgentLoop
from querybridge.connectors.base import DatabaseConnector
from querybridge.core.config import EngineConfig
from querybridge.core.models import QueryRequest, QueryResponse
from querybridge.llm.base import LLMProvider
from querybridge.memory.store import MemoryStore
from querybridge.plugins.base import DomainPlugin
from querybridge.plugins.builtin.generic import GenericPlugin
from querybridge.plugins.registry import PluginRegistry
from querybridge.prompts.few_shot import FewShotRegistry
from querybridge.schema.cache import SchemaCache

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
        config: Optional[EngineConfig] = None,
        plugin: Optional[DomainPlugin] = None,
    ):
        self.connector = connector
        self.llm = llm
        self.config = config or EngineConfig()
        self.plugin = plugin or GenericPlugin()
        self.schema_cache = SchemaCache(connector, self.plugin)
        self.memory_store = MemoryStore(
            max_sessions=100, session_ttl=self.config.session_ttl
        )
        self.few_shot = FewShotRegistry()

        # Register plugin few-shot examples
        for ex in self.plugin.get_few_shot_examples():
            self.few_shot.add(
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
        chat_id: Optional[str] = None,
        history: Optional[list] = None,
    ) -> QueryResponse:
        """Execute a natural language query."""
        request = QueryRequest(
            question=question,
            chat_id=chat_id,
            history=history or [],
        )
        return await self._agent.run(request)

    async def close(self):
        """Clean up resources."""
        await self.connector.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()

    @classmethod
    def from_config(
        cls,
        connector: DatabaseConnector,
        llm: LLMProvider,
        config_dict: Optional[Dict[str, Any]] = None,
        plugin_name: Optional[str] = None,
    ) -> "QueryBridgeEngine":
        """Create an engine from a config dict and optional plugin name."""
        config = EngineConfig(**(config_dict or {}))

        plugin: Optional[DomainPlugin] = None
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
