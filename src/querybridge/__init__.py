"""
QueryBridge — NL2SQL Engine.

Connect any database. Ask questions in plain English. Get accurate SQL-backed answers.
"""

from querybridge.core.engine import QueryBridgeEngine
from querybridge.core.config import EngineConfig
from querybridge.core.models import QueryResponse, QueryRequest
from querybridge.connectors.base import DatabaseConnector
from querybridge.llm.base import LLMProvider
from querybridge.plugins.base import DomainPlugin

__version__ = "0.1.0"

__all__ = [
    "QueryBridgeEngine",
    "EngineConfig",
    "QueryResponse",
    "QueryRequest",
    "DatabaseConnector",
    "LLMProvider",
    "DomainPlugin",
]
