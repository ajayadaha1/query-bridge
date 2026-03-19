"""PersistentQueryMemory — SQLite-backed cross-session query memory.

Stores successful question→SQL pairs so that future similar questions
can retrieve past examples as few-shot context. Supports two recall modes:
1. Keyword similarity (Jaccard) — always available, no dependencies
2. Embedding similarity (cosine) — when an embedding provider is configured
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("querybridge.memory.persistent")

_DEFAULT_DB_DIR = "/tmp/querybridge_cache"
_DEFAULT_DB_NAME = "query_memory.db"


@dataclass
class StoredQuery:
    """A stored question→SQL pair with metadata."""
    id: int
    question: str
    sql: str
    datasource: str
    question_type: str
    confidence: float
    row_count: int
    created_at: float
    keywords: list[str]


def _tokenize(text: str) -> list[str]:
    """Extract meaningful tokens from a question for keyword matching."""
    text = text.lower()
    # Remove common SQL-irrelevant stop words
    stop_words = {
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "can", "shall", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "into", "through", "during",
        "before", "after", "above", "below", "between", "and", "but", "or",
        "nor", "not", "so", "yet", "both", "either", "neither", "each",
        "every", "all", "any", "few", "more", "most", "other", "some",
        "such", "no", "only", "own", "same", "than", "too", "very",
        "just", "because", "about", "up", "out", "off", "over", "under",
        "again", "further", "then", "once", "here", "there", "when",
        "where", "why", "how", "what", "which", "who", "whom", "this",
        "that", "these", "those", "i", "me", "my", "we", "our", "you",
        "your", "he", "him", "his", "she", "her", "it", "its", "they",
        "them", "their", "show", "give", "tell", "list", "find", "get",
        "display", "please", "want", "need", "like",
    }
    tokens = re.findall(r"[a-z][a-z0-9_]+", text)
    return [t for t in tokens if t not in stop_words and len(t) > 1]


def _keyword_similarity(q1_keywords: list[str], q2_keywords: list[str]) -> float:
    """Compute Jaccard-like similarity between two keyword sets."""
    if not q1_keywords or not q2_keywords:
        return 0.0
    s1 = Counter(q1_keywords)
    s2 = Counter(q2_keywords)
    intersection = sum((s1 & s2).values())
    union = sum((s1 | s2).values())
    if union == 0:
        return 0.0
    return intersection / union


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


# Type for embedding functions: (text) -> list[float]
EmbeddingFn = Callable[[str], list[float]]


class PersistentQueryMemory:
    """SQLite-backed persistent query memory for cross-session learning.

    Supports optional embedding-based recall when an embedding function is provided.
    Falls back to keyword similarity when embeddings are not available.
    """

    def __init__(
        self,
        db_dir: str = _DEFAULT_DB_DIR,
        datasource: str = "default",
        embed_fn: EmbeddingFn | None = None,
    ):
        self._datasource = datasource
        self._db_path = Path(db_dir) / _DEFAULT_DB_NAME
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._embed_fn = embed_fn
        self._init_db()

    def _init_db(self):
        """Create the query_memory table if it doesn't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS query_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    sql_text TEXT NOT NULL,
                    datasource TEXT NOT NULL,
                    question_type TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    row_count INTEGER DEFAULT 0,
                    keywords TEXT DEFAULT '[]',
                    embedding TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    times_retrieved INTEGER DEFAULT 0
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_qm_datasource
                ON query_memory(datasource)
            """)
            # Add embedding column for existing DBs
            try:
                conn.execute("SELECT embedding FROM query_memory LIMIT 1")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE query_memory ADD COLUMN embedding TEXT DEFAULT ''")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self._db_path), timeout=5)

    def store(
        self,
        question: str,
        sql: str,
        question_type: str = "",
        confidence: float = 0.0,
        row_count: int = 0,
    ):
        """Store a successful question→SQL pair."""
        keywords = _tokenize(question)
        embedding_json = ""
        if self._embed_fn:
            try:
                embedding = self._embed_fn(question)
                embedding_json = json.dumps(embedding)
            except Exception as e:
                logger.debug(f"Embedding generation failed: {e}")

        with self._connect() as conn:
            # Avoid exact duplicates
            existing = conn.execute(
                "SELECT id FROM query_memory WHERE question = ? AND datasource = ?",
                (question, self._datasource),
            ).fetchone()
            if existing:
                # Update the SQL if the question already exists
                conn.execute(
                    """UPDATE query_memory
                       SET sql_text = ?, confidence = ?, row_count = ?,
                           keywords = ?, embedding = ?, created_at = ?
                       WHERE id = ?""",
                    (sql, confidence, row_count,
                     json.dumps(keywords), embedding_json, time.time(), existing[0]),
                )
                return

            conn.execute(
                """INSERT INTO query_memory
                   (question, sql_text, datasource, question_type,
                    confidence, row_count, keywords, embedding, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (question, sql, self._datasource, question_type,
                 confidence, row_count, json.dumps(keywords), embedding_json, time.time()),
            )
        logger.debug(f"Stored query memory: {question[:60]}...")

    def recall(
        self,
        question: str,
        limit: int = 3,
        min_similarity: float = 0.25,
        min_confidence: float = 0.5,
    ) -> list[StoredQuery]:
        """Retrieve similar past queries.

        Uses embedding similarity when available, falls back to keyword similarity.
        """
        if self._embed_fn:
            try:
                results = self._recall_by_embedding(question, limit, min_similarity, min_confidence)
                if results:
                    return results
            except Exception as e:
                logger.debug(f"Embedding recall failed, falling back to keywords: {e}")

        return self._recall_by_keywords(question, limit, min_similarity, min_confidence)

    def _recall_by_keywords(
        self,
        question: str,
        limit: int,
        min_similarity: float,
        min_confidence: float,
    ) -> list[StoredQuery]:
        """Keyword-based recall (Jaccard similarity)."""
        question_keywords = _tokenize(question)
        if not question_keywords:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, question, sql_text, datasource, question_type,
                          confidence, row_count, created_at, keywords
                   FROM query_memory
                   WHERE datasource = ? AND confidence >= ?
                   ORDER BY created_at DESC
                   LIMIT 200""",
                (self._datasource, min_confidence),
            ).fetchall()

        # Score by keyword similarity
        scored: list[tuple[float, StoredQuery]] = []
        for row in rows:
            stored_keywords = json.loads(row[8]) if row[8] else []
            sim = _keyword_similarity(question_keywords, stored_keywords)
            if sim >= min_similarity:
                sq = StoredQuery(
                    id=row[0], question=row[1], sql=row[2],
                    datasource=row[3], question_type=row[4],
                    confidence=row[5], row_count=row[6],
                    created_at=row[7], keywords=stored_keywords,
                )
                scored.append((sim, sq))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [sq for _, sq in scored[:limit]]

        if results:
            self._update_retrieval_counts(results)
        return results

    def _recall_by_embedding(
        self,
        question: str,
        limit: int,
        min_similarity: float,
        min_confidence: float,
    ) -> list[StoredQuery]:
        """Embedding-based recall (cosine similarity)."""
        query_embedding = self._embed_fn(question)
        if not query_embedding:
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT id, question, sql_text, datasource, question_type,
                          confidence, row_count, created_at, keywords, embedding
                   FROM query_memory
                   WHERE datasource = ? AND confidence >= ? AND embedding != ''
                   ORDER BY created_at DESC
                   LIMIT 200""",
                (self._datasource, min_confidence),
            ).fetchall()

        scored: list[tuple[float, StoredQuery]] = []
        for row in rows:
            try:
                stored_embedding = json.loads(row[9])
            except (json.JSONDecodeError, IndexError):
                continue
            sim = _cosine_similarity(query_embedding, stored_embedding)
            if sim >= min_similarity:
                sq = StoredQuery(
                    id=row[0], question=row[1], sql=row[2],
                    datasource=row[3], question_type=row[4],
                    confidence=row[5], row_count=row[6],
                    created_at=row[7], keywords=json.loads(row[8]) if row[8] else [],
                )
                scored.append((sim, sq))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [sq for _, sq in scored[:limit]]

        if results:
            self._update_retrieval_counts(results)
        return results

    def _update_retrieval_counts(self, results: list[StoredQuery]):
        """Increment times_retrieved counter for recalled queries."""
        with self._connect() as conn:
            for sq in results:
                conn.execute(
                    "UPDATE query_memory SET times_retrieved = times_retrieved + 1 WHERE id = ?",
                    (sq.id,),
                )

    def format_as_few_shot(self, stored_queries: list[StoredQuery]) -> list[dict[str, str]]:
        """Convert stored queries to few-shot example format."""
        return [
            {
                "question": sq.question,
                "sql": sq.sql,
                "explanation": f"Past query (confidence: {sq.confidence:.0%})",
            }
            for sq in stored_queries
        ]

    def get_stats(self) -> dict:
        """Return stats about stored queries."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM query_memory WHERE datasource = ?",
                (self._datasource,),
            ).fetchone()[0]
            top_types = conn.execute(
                """SELECT question_type, COUNT(*) as cnt
                   FROM query_memory WHERE datasource = ?
                   GROUP BY question_type ORDER BY cnt DESC LIMIT 5""",
                (self._datasource,),
            ).fetchall()
        return {
            "total_stored": total,
            "top_question_types": {r[0]: r[1] for r in top_types},
        }

    def clear(self):
        """Clear all stored queries for the current datasource."""
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM query_memory WHERE datasource = ?",
                (self._datasource,),
            )
