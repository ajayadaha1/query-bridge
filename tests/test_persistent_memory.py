"""Tests for PersistentQueryMemory."""

import os
import tempfile

import pytest

from querybridge.memory.persistent import (
    PersistentQueryMemory,
    _keyword_similarity,
    _tokenize,
)


class TestTokenize:
    def test_basic(self):
        tokens = _tokenize("How many artists are there?")
        assert "artists" in tokens
        assert "many" in tokens
        # Stop words filtered out
        assert "how" not in tokens
        assert "are" not in tokens
        assert "there" not in tokens

    def test_sql_terms(self):
        tokens = _tokenize("Show me the failure rate by customer")
        assert "failure" in tokens
        assert "rate" in tokens
        assert "customer" in tokens

    def test_empty(self):
        assert _tokenize("") == []

    def test_short_tokens_removed(self):
        tokens = _tokenize("a b c de fg hi")
        assert "a" not in tokens
        assert "b" not in tokens


class TestKeywordSimilarity:
    def test_identical(self):
        kw = ["failure", "rate", "customer"]
        assert _keyword_similarity(kw, kw) == 1.0

    def test_no_overlap(self):
        assert _keyword_similarity(["failure", "rate"], ["artist", "album"]) == 0.0

    def test_partial_overlap(self):
        sim = _keyword_similarity(
            ["failure", "rate", "customer"],
            ["failure", "rate", "error"],
        )
        assert 0.3 < sim < 0.8

    def test_empty(self):
        assert _keyword_similarity([], ["test"]) == 0.0
        assert _keyword_similarity(["test"], []) == 0.0


class TestPersistentQueryMemory:
    @pytest.fixture
    def memory(self, tmp_path):
        return PersistentQueryMemory(db_dir=str(tmp_path), datasource="test")

    def test_store_and_recall(self, memory):
        memory.store(
            question="How many assets per customer?",
            sql="SELECT customer_normalized, COUNT(*) FROM analysis_facts GROUP BY 1",
            question_type="count",
            confidence=0.9,
            row_count=15,
        )
        results = memory.recall("assets by customer", min_similarity=0.2)
        assert len(results) >= 1
        assert "customer_normalized" in results[0].sql

    def test_no_duplicates(self, memory):
        for _ in range(3):
            memory.store(
                question="How many artists?",
                sql="SELECT COUNT(*) FROM artist",
                confidence=0.95,
            )
        stats = memory.get_stats()
        assert stats["total_stored"] == 1

    def test_recall_respects_min_confidence(self, memory):
        memory.store(
            question="Low confidence query",
            sql="SELECT 1",
            confidence=0.2,
        )
        results = memory.recall("Low confidence query", min_confidence=0.5)
        assert len(results) == 0

    def test_recall_no_match(self, memory):
        memory.store(
            question="How many artists?",
            sql="SELECT COUNT(*) FROM artist",
            confidence=0.9,
        )
        results = memory.recall("weather forecast tomorrow", min_similarity=0.3)
        assert len(results) == 0

    def test_datasource_isolation(self, tmp_path):
        mem_a = PersistentQueryMemory(db_dir=str(tmp_path), datasource="db_a")
        mem_b = PersistentQueryMemory(db_dir=str(tmp_path), datasource="db_b")

        mem_a.store(question="semiconductor failure rate by customer", sql="SELECT customer_normalized FROM analysis_facts", confidence=0.9)
        mem_b.store(question="best selling music albums worldwide", sql="SELECT name FROM albums", confidence=0.9)

        assert mem_a.get_stats()["total_stored"] == 1
        assert mem_b.get_stats()["total_stored"] == 1
        # mem_a should find its own query
        assert len(mem_a.recall("semiconductor failures customer", min_similarity=0.2)) >= 1
        # mem_a should NOT find mem_b's music query (different datasource)
        assert len(mem_a.recall("best selling music albums worldwide", min_similarity=0.2)) == 0

    def test_format_as_few_shot(self, memory):
        memory.store(
            question="Top customers by failure count",
            sql="SELECT customer_normalized, COUNT(*) FROM analysis_facts GROUP BY 1 ORDER BY 2 DESC LIMIT 10",
            confidence=0.85,
        )
        results = memory.recall("customers failures", min_similarity=0.2)
        few_shot = memory.format_as_few_shot(results)
        assert len(few_shot) >= 1
        assert "question" in few_shot[0]
        assert "sql" in few_shot[0]
        assert "explanation" in few_shot[0]

    def test_clear(self, memory):
        memory.store(question="test query", sql="SELECT 1", confidence=0.9)
        assert memory.get_stats()["total_stored"] == 1
        memory.clear()
        assert memory.get_stats()["total_stored"] == 0

    def test_stats(self, memory):
        memory.store(question="count query 1", sql="SELECT COUNT(*) FROM t1", question_type="count", confidence=0.9)
        memory.store(question="search for records", sql="SELECT * FROM t2", question_type="search", confidence=0.8)
        stats = memory.get_stats()
        assert stats["total_stored"] == 2
        assert "count" in stats["top_question_types"]
