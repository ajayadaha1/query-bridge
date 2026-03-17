"""Pluggable entity extraction — combines base patterns with plugin patterns."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple


class EntityExtractor:
    """Extracts entities from natural language using regex patterns."""

    def __init__(self, patterns: Optional[Dict[str, List[str]]] = None):
        self._compiled: Dict[str, List[re.Pattern]] = {}
        if patterns:
            self.add_patterns(patterns)

    def add_patterns(self, patterns: Dict[str, List[str]]):
        """Add entity patterns. Key format: 'entity_type:value' or 'entity_type'."""
        for key, regex_list in patterns.items():
            self._compiled[key] = [
                re.compile(p, re.IGNORECASE) for p in regex_list
            ]

    def extract(self, text: str) -> Tuple[List[str], List[str]]:
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
