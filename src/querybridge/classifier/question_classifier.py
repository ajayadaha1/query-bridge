"""QuestionClassifier — Pre-LLM heuristic classification for NL2SQL queries."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from querybridge.classifier.patterns import (
    QUESTION_TYPE_PATTERNS,
    COMPLEXITY_PATTERNS,
)
from querybridge.classifier.entity_extractor import EntityExtractor


@dataclass
class QuestionProfile:
    """Structured metadata extracted from a user question."""
    question_type: str = "drill_down"
    expected_shape: str = "table"
    implied_entities: List[str] = field(default_factory=list)
    implied_columns: List[str] = field(default_factory=list)
    complexity: str = "simple"
    needs_discovery: bool = False
    phase_budgets: Dict[str, int] = field(default_factory=dict)
    confidence: float = 0.0

    def __post_init__(self):
        if not self.phase_budgets:
            self.phase_budgets = self._default_budgets()

    def _default_budgets(self) -> Dict[str, int]:
        if self.complexity == "simple":
            return {"explore": 1, "execute": 3, "validate": 1, "refine": 0}
        elif self.complexity == "moderate":
            return {"explore": 2, "execute": 4, "validate": 2, "refine": 2}
        else:
            return {"explore": 3, "execute": 5, "validate": 3, "refine": 4}


class QuestionClassifier:
    """Heuristic classifier for NL2SQL questions.

    Combines generic question-type patterns with optional plugin-provided
    entity patterns and column mappings.
    """

    def __init__(
        self,
        entity_patterns: Optional[Dict[str, List[str]]] = None,
        entity_column_map: Optional[Dict[str, List[str]]] = None,
        extra_question_patterns: Optional[Dict[str, List[str]]] = None,
    ):
        # Compile question type patterns
        self._qtype_compiled: Dict[str, List[re.Pattern]] = {
            qtype: [re.compile(p, re.IGNORECASE) for p in patterns]
            for qtype, patterns in QUESTION_TYPE_PATTERNS.items()
        }
        # Add plugin question patterns
        if extra_question_patterns:
            for qtype, patterns in extra_question_patterns.items():
                compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
                if qtype in self._qtype_compiled:
                    self._qtype_compiled[qtype].extend(compiled)
                else:
                    self._qtype_compiled[qtype] = compiled

        # Compile complexity patterns
        self._complexity_compiled: Dict[str, List[re.Pattern]] = {
            level: [re.compile(p, re.IGNORECASE) for p in patterns]
            for level, patterns in COMPLEXITY_PATTERNS.items()
        }

        # Entity extraction
        self._entity_extractor = EntityExtractor(entity_patterns)
        self._entity_column_map = entity_column_map or {}

    def classify(self, question: str) -> QuestionProfile:
        if not question or not question.strip():
            return QuestionProfile(question_type="unknown", expected_shape="unknown")

        question = question.strip()

        # Extract entities
        entities, _ = self._entity_extractor.extract(question)

        # Classify question type
        question_type, confidence = self._classify_type(question)

        # Determine expected shape
        expected_shape = self._infer_shape(question_type, question)

        # Assess complexity
        complexity = self._assess_complexity(question, entities)

        # Infer columns from entities
        columns = self._infer_columns(entities)

        needs_discovery = len(entities) > 0

        return QuestionProfile(
            question_type=question_type,
            expected_shape=expected_shape,
            implied_entities=entities,
            implied_columns=columns,
            complexity=complexity,
            needs_discovery=needs_discovery,
            confidence=round(min(confidence + 0.1 * len(entities), 1.0), 2),
        )

    def _classify_type(self, question: str) -> Tuple[str, float]:
        scores: Dict[str, float] = {}
        for qtype, patterns in self._qtype_compiled.items():
            score = sum(1.0 for p in patterns if p.search(question))
            scores[qtype] = score

        if not scores or max(scores.values()) == 0:
            return "drill_down", 0.3

        best = max(scores, key=scores.get)
        total = sum(scores.values())
        conf = scores[best] / total if total > 0 else 0.3
        return best, conf

    def _infer_shape(self, qtype: str, question: str) -> str:
        shape_map = {
            "count": "scalar", "comparison": "grouped", "trend": "time_series",
            "drill_down": "table", "audit": "table", "search": "table",
        }
        base = shape_map.get(qtype, "table")
        if re.search(r"\bby\s+\w+\b", question, re.IGNORECASE):
            return "grouped"
        if re.search(r"\b(monthly|weekly|daily)\b", question, re.IGNORECASE):
            return "time_series"
        return base

    def _assess_complexity(self, question: str, entities: List[str]) -> str:
        for pattern in self._complexity_compiled.get("complex", []):
            if pattern.search(question):
                return "complex"
        for pattern in self._complexity_compiled.get("moderate", []):
            if pattern.search(question):
                return "moderate"
        if len(entities) > 3:
            return "moderate"
        return "simple"

    def _infer_columns(self, entities: List[str]) -> List[str]:
        columns = set()
        for entity in entities:
            entity_type = entity.split(":")[0] if ":" in entity else entity
            if entity_type in self._entity_column_map:
                columns.update(self._entity_column_map[entity_type])
        return list(columns)


def classify_question(
    question: str,
    entity_patterns: Optional[Dict[str, List[str]]] = None,
    entity_column_map: Optional[Dict[str, List[str]]] = None,
) -> QuestionProfile:
    """Convenience function."""
    return QuestionClassifier(
        entity_patterns=entity_patterns,
        entity_column_map=entity_column_map,
    ).classify(question)
