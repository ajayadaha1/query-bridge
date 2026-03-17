"""Pluggable entity extraction — combines base patterns with plugin patterns."""

from __future__ import annotations

import re


class EntityExtractor:
    """Extracts entities from natural language using regex patterns."""

    def __init__(self, patterns: dict[str, list[str]] | None = None):
        self._compiled: dict[str, list[re.Pattern]] = {}
        if patterns:
            self.add_patterns(patterns)

    def add_patterns(self, patterns: dict[str, list[str]]):
        """Add entity patterns. Key format: 'entity_type:value' or 'entity_type'."""
        for key, regex_list in patterns.items():
            self._compiled[key] = [
                re.compile(p, re.IGNORECASE) for p in regex_list
            ]

    def extract(self, text: str) -> tuple[list[str], list[str]]:
        """Extract entities from text.

        Returns: (entities, matched_pattern_labels)
        """
        entities = []
        matches = []
        for key, patterns in self._compiled.items():
            for pattern in patterns:
                if pattern.search(text):
                    entities.append(key)
                    matches.append(key)
                    break
        return entities, matches
