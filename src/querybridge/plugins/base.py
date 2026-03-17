"""DomainPlugin — Abstract base class for domain-specific knowledge injection."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from querybridge.core.models import ToolDefinition


class DomainPlugin(ABC):
    """Inject domain-specific knowledge into the NL2SQL engine."""

    @abstractmethod
    def get_name(self) -> str:
        """Plugin name (e.g., 'silicon-trace', 'ecommerce', 'finance')."""

    def get_entity_patterns(self) -> dict[str, list[str]]:
        """Regex patterns for entity extraction.
        Returns {entity_key: [regex_pattern, ...]}"""
        return {}

    def get_entity_column_map(self) -> dict[str, list[str]]:
        """Map entity types to candidate database columns.
        Returns {entity_type: [column_name, ...]}"""
        return {}

    def get_column_annotations(self) -> dict[str, str]:
        """Human-readable descriptions for columns.
        Returns {column_name: description}"""
        return {}

    def get_column_hierarchy(self) -> list[list[str]]:
        """Column escalation paths for strategy tracker.
        Returns [[most_specific, ..., least_specific], ...]"""
        return []

    def get_system_prompt_context(self) -> str:
        """Additional domain context injected into the system prompt."""
        return ""

    def get_few_shot_examples(self) -> list[dict[str, str]]:
        """Domain-specific few-shot SQL examples.
        Returns [{question: str, sql: str, explanation: str}, ...]"""
        return []

    def get_question_type_patterns(self) -> dict[str, list[str]]:
        """Additional question type regex patterns.
        Returns {question_type: [regex, ...]}"""
        return {}

    def get_custom_tools(self) -> list[ToolDefinition]:
        """Register domain-specific tools for the agent.
        Returns list of tool definitions the LLM can call."""
        return []

    def get_response_formatting_rules(self) -> str:
        """Domain-specific response formatting instructions."""
        return ""

    def get_primary_table(self) -> str | None:
        """Return the name of the primary table for this domain, if any."""
        return None
