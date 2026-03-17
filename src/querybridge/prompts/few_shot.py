"""Few-shot example registry."""

from __future__ import annotations

from typing import Dict, List


class FewShotRegistry:
    """Manages few-shot SQL examples from plugins and built-in patterns."""

    def __init__(self):
        self._examples: List[Dict[str, str]] = []

    def add_example(self, question: str, sql: str, explanation: str = ""):
        self._examples.append({
            "question": question, "sql": sql, "explanation": explanation,
        })

    def add_examples(self, examples: List[Dict[str, str]]):
        for ex in examples:
            self.add_example(
                question=ex["question"], sql=ex["sql"],
                explanation=ex.get("explanation", ""),
            )

    def get_examples(self, limit: int = 10) -> List[Dict[str, str]]:
        return self._examples[:limit]

    def format_for_prompt(self, limit: int = 10) -> str:
        examples = self.get_examples(limit)
        if not examples:
            return ""
        lines = ["## Few-Shot Examples"]
        for ex in examples:
            lines.append(f"\nQ: {ex['question']}")
            lines.append(f"```sql\n{ex['sql']}\n```")
            if ex.get("explanation"):
                lines.append(f"→ {ex['explanation']}")
        return "\n".join(lines)
