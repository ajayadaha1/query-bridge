"""RAG Sync — Bridge between QueryBridge's PersistentQueryMemory and
Silicon Trace's rag_query_memory (PostgreSQL + pgvector).

Pushes successful query→SQL pairs to the shared rag_query_memory table
so that all services (Silicon Trace AI processor, QueryBridge, etc.)
benefit from the same growing knowledge base.

Also supports recall: given a question, queries rag_query_memory using
pgvector cosine similarity for high-quality semantic matches.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Callable

logger = logging.getLogger("querybridge.memory.rag_sync")

# Type for embedding functions: (text) -> list[float]
EmbeddingFn = Callable[[str], list[float]]


@dataclass
class RAGMatch:
    """A match from rag_query_memory."""
    id: int
    question: str
    sql_queries: list[dict[str, Any]]
    answer_summary: str
    quality_score: float
    similarity: float


def _parse_pg_dsn(dsn: str) -> str:
    """Convert asyncpg DSN to psycopg-compatible DSN for sync access.

    Input:  postgresql+asyncpg://user:pass@host:5432/db
    Output: postgresql://user:pass@host:5432/db
    """
    return dsn.replace("postgresql+asyncpg://", "postgresql://")


class RAGSync:
    """Sync bridge to Silicon Trace's rag_query_memory table.

    Uses asyncpg for async read/write operations against the pgvector-backed
    rag_query_memory table in the Silicon Trace PostgreSQL database.
    """

    def __init__(
        self,
        pg_dsn: str | None = None,
        embed_fn: EmbeddingFn | None = None,
    ):
        self._dsn = pg_dsn or os.getenv(
            "QUERYBRIDGE_DSN",
            "postgresql+asyncpg://silicon_user:silicon_pass@silicon_trace_db:5432/silicon_trace_db",
        )
        # Normalise to plain postgresql:// for asyncpg
        self._dsn_clean = self._dsn.replace("postgresql+asyncpg://", "postgresql://")
        self._embed_fn = embed_fn
        self._pool: Any = None

    async def _get_pool(self):
        """Lazily create an asyncpg connection pool."""
        if self._pool is None:
            try:
                import asyncpg
                self._pool = await asyncpg.create_pool(
                    self._dsn_clean, min_size=1, max_size=3, timeout=10,
                )
            except Exception as e:
                logger.warning("RAGSync: failed to create pool: %s", e)
                raise
        return self._pool

    async def push(
        self,
        question: str,
        sql: str,
        answer_summary: str = "",
        quality_score: float = 0.5,
        iterations_used: int = 1,
        row_count: int = 0,
        had_errors: bool = False,
    ) -> int | None:
        """Push a query→SQL pair to rag_query_memory.

        Returns the inserted row ID, or None on failure.
        """
        try:
            pool = await self._get_pool()
        except Exception:
            return None

        embedding = None
        if self._embed_fn:
            try:
                embedding = self._embed_fn(question)
            except Exception as e:
                logger.debug("RAGSync: embedding generation failed: %s", e)

        sql_queries = json.dumps([{"sql": sql, "source": "querybridge"}])

        try:
            async with pool.acquire() as conn:
                # Check for duplicate question
                existing = await conn.fetchval(
                    "SELECT id FROM rag_query_memory WHERE question = $1",
                    question,
                )
                if existing:
                    # Update existing entry
                    await conn.execute(
                        """UPDATE rag_query_memory
                           SET sql_queries = $1, answer_summary = $2,
                               quality_score = $3, iterations_used = $4,
                               result_row_count = $5, had_errors = $6,
                               updated_at = now()
                           WHERE id = $7""",
                        sql_queries, answer_summary, quality_score,
                        iterations_used, row_count, had_errors, existing,
                    )
                    logger.debug("RAGSync: updated existing entry id=%s", existing)
                    return existing

                # Insert new row
                if embedding:
                    row_id = await conn.fetchval(
                        """INSERT INTO rag_query_memory
                           (question, embedding, sql_queries, answer_summary,
                            quality_score, iterations_used, result_row_count, had_errors)
                           VALUES ($1, $2::vector, $3::jsonb, $4, $5, $6, $7, $8)
                           RETURNING id""",
                        question, str(embedding), sql_queries, answer_summary,
                        quality_score, iterations_used, row_count, had_errors,
                    )
                else:
                    row_id = await conn.fetchval(
                        """INSERT INTO rag_query_memory
                           (question, sql_queries, answer_summary,
                            quality_score, iterations_used, result_row_count, had_errors)
                           VALUES ($1, $2::jsonb, $3, $4, $5, $6, $7)
                           RETURNING id""",
                        question, sql_queries, answer_summary,
                        quality_score, iterations_used, row_count, had_errors,
                    )
                logger.debug("RAGSync: inserted new entry id=%s", row_id)
                return row_id
        except Exception as e:
            logger.warning("RAGSync: push failed: %s", e)
            return None

    async def recall(
        self,
        question: str,
        limit: int = 5,
        min_quality: float = 0.5,
    ) -> list[RAGMatch]:
        """Recall similar queries from rag_query_memory using pgvector similarity.

        Falls back to text search if embeddings are not available.
        """
        try:
            pool = await self._get_pool()
        except Exception:
            return []

        # Try embedding-based recall first (pgvector cosine distance)
        if self._embed_fn:
            try:
                embedding = self._embed_fn(question)
                return await self._recall_by_vector(pool, embedding, limit, min_quality)
            except Exception as e:
                logger.debug("RAGSync: vector recall failed, trying text: %s", e)

        # Fallback: trigram/ILIKE text search
        return await self._recall_by_text(pool, question, limit, min_quality)

    async def _recall_by_vector(
        self,
        pool: Any,
        embedding: list[float],
        limit: int,
        min_quality: float,
    ) -> list[RAGMatch]:
        """Recall using pgvector cosine distance operator (<=>)."""
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, question, sql_queries, answer_summary, quality_score,
                          1 - (embedding <=> $1::vector) as similarity
                   FROM rag_query_memory
                   WHERE quality_score >= $2 AND embedding IS NOT NULL
                   ORDER BY embedding <=> $1::vector
                   LIMIT $3""",
                str(embedding), min_quality, limit,
            )
        return [
            RAGMatch(
                id=r["id"],
                question=r["question"],
                sql_queries=json.loads(r["sql_queries"]) if r["sql_queries"] else [],
                answer_summary=r["answer_summary"] or "",
                quality_score=r["quality_score"],
                similarity=r["similarity"],
            )
            for r in rows
        ]

    async def _recall_by_text(
        self,
        pool: Any,
        question: str,
        limit: int,
        min_quality: float,
    ) -> list[RAGMatch]:
        """Fallback text-based recall using ILIKE."""
        # Extract key terms for search
        words = [w for w in question.lower().split() if len(w) > 3]
        if not words:
            return []

        # Build ILIKE conditions for top keywords (max 5)
        conditions = []
        params = [min_quality]
        for i, w in enumerate(words[:5], start=2):
            conditions.append(f"question ILIKE ${i}")
            params.append(f"%{w}%")

        where = " OR ".join(conditions) if conditions else "TRUE"
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""SELECT id, question, sql_queries, answer_summary, quality_score
                   FROM rag_query_memory
                   WHERE quality_score >= $1 AND ({where})
                   ORDER BY quality_score DESC, updated_at DESC
                   LIMIT ${len(params)}""",
                *params,
            )
        return [
            RAGMatch(
                id=r["id"],
                question=r["question"],
                sql_queries=json.loads(r["sql_queries"]) if r["sql_queries"] else [],
                answer_summary=r["answer_summary"] or "",
                quality_score=r["quality_score"],
                similarity=0.5,  # placeholder for text matches
            )
            for r in rows
        ]

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None
