"""Fuzzy matching utilities."""

from difflib import SequenceMatcher
import re


def fuzzy_ratio(s1: str, s2: str) -> float:
    """Compute normalized similarity ratio between two strings."""
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()


def normalize_value(value: str) -> str:
    """Normalize a value for comparison: remove separators, lowercase."""
    return re.sub(r"[-_\s]+", "", value.lower())
