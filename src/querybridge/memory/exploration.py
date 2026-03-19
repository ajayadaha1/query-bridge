"""ExplorationMemory — Persistent exploration knowledge store.

The agent writes notes to itself about what it discovers during exploration
(table profiles, column relevance, relationships, query paths, safety warnings).
These notes survive across conversations so the agent never re-explores the
same ground twice.

Storage: SQLite with FTS5 for full-text search.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("querybridge.memory.exploration")

_DEFAULT_DB_DIR = "/tmp/querybridge_cache"
_DEFAULT_DB_NAME = "exploration_memory.db"

# Valid note types
NOTE_TYPES = frozenset({
    "table_profile",
    "column_relevance",
    "relationship",
    "query_path",
    "schema_map",
    "routing_outcome",
    "safety_warning",
    "negative_knowledge",
})


@dataclass
class ExplorationNote:
    """A persistent exploration observation."""

    id: str
    datasource: str
    note_type: str
    subject: str
    content: str
    structured_data: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.7
    source_question: str = ""
    created_at: float = 0.0
    last_used_at: float = 0.0
    times_used: int = 0
    keywords: list[str] = field(default_factory=list)


def _extract_keywords(text: str) -> list[str]:
    """Extract meaningful tokens for keyword search."""
    text = text.lower()
    stop = {
        "the", "a", "an", "is", "are", "was", "be", "have", "has", "do",
        "does", "will", "would", "could", "should", "to", "of", "in", "for",
        "on", "with", "at", "by", "from", "as", "and", "but", "or", "not",
        "this", "that", "use", "using", "used", "table", "column", "rows",
    }
    tokens = re.findall(r"[a-z][a-z0-9_]+", text)
    return list(dict.fromkeys(t for t in tokens if t not in stop and len(t) > 1))


class ExplorationMemory:
    """SQLite-backed persistent exploration memory with FTS5 search.

    Stores notes the agent writes about discovered schema structure,
    table profiles, relationships, query paths, and safety warnings.
    """

    def __init__(self, db_dir: str = _DEFAULT_DB_DIR, datasource: str = "default"):
        self._datasource = datasource
        self._db_path = Path(db_dir) / _DEFAULT_DB_NAME
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self._db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """Create tables and FTS5 virtual table."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS exploration_notes (
                    id              TEXT PRIMARY KEY,
                    datasource      TEXT NOT NULL,
                    note_type       TEXT NOT NULL,
                    subject         TEXT NOT NULL,
                    content         TEXT NOT NULL,
                    structured_data TEXT DEFAULT '{}',
                    confidence      REAL DEFAULT 0.7,
                    source_question TEXT DEFAULT '',
                    created_at      REAL NOT NULL,
                    last_used_at    REAL NOT NULL,
                    times_used      INTEGER DEFAULT 0,
                    keywords        TEXT DEFAULT '[]'
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_datasource
                ON exploration_notes(datasource)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_type
                ON exploration_notes(datasource, note_type)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_notes_subject
                ON exploration_notes(subject)
            """)
            # FTS5 for full-text search (content-less, external content)
            # Using a separate FTS table that we manually sync
            try:
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS exploration_notes_fts
                    USING fts5(subject, content, keywords, content='', content_rowid='')
                """)
            except sqlite3.OperationalError:
                # FTS5 may not be available — degrade gracefully to keyword search
                logger.info("FTS5 not available, falling back to LIKE-based search")

    # ------------------------------------------------------------------
    # Core note operations
    # ------------------------------------------------------------------

    def note(
        self,
        note_type: str,
        subject: str,
        content: str,
        structured_data: dict[str, Any] | None = None,
        confidence: float = 0.7,
        source_question: str = "",
    ) -> str:
        """Store an exploration note. Deduplicates by (datasource, note_type, subject).

        If a note with the same datasource/note_type/subject exists, it is
        superseded: old note's confidence is halved, new note replaces it.

        Returns the note ID.
        """
        now = time.time()
        note_id = str(uuid.uuid4())[:12]
        keywords = _extract_keywords(f"{subject} {content}")

        with self._connect() as conn:
            # Supersede existing note for same subject+type
            existing = conn.execute(
                "SELECT id, confidence FROM exploration_notes "
                "WHERE datasource = ? AND note_type = ? AND subject = ?",
                (self._datasource, note_type, subject),
            ).fetchone()

            if existing:
                # Update in place rather than creating a duplicate
                conn.execute(
                    """UPDATE exploration_notes
                       SET content = ?, structured_data = ?, confidence = ?,
                           source_question = ?, last_used_at = ?, keywords = ?
                       WHERE id = ?""",
                    (
                        content,
                        json.dumps(structured_data or {}),
                        confidence,
                        source_question,
                        now,
                        json.dumps(keywords),
                        existing["id"],
                    ),
                )
                note_id = existing["id"]
                self._update_fts(conn, note_id, subject, content, keywords)
                logger.debug("Updated exploration note %s: %s/%s", note_id, note_type, subject)
                return note_id

            conn.execute(
                """INSERT INTO exploration_notes
                   (id, datasource, note_type, subject, content, structured_data,
                    confidence, source_question, created_at, last_used_at, keywords)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    note_id, self._datasource, note_type, subject, content,
                    json.dumps(structured_data or {}), confidence, source_question,
                    now, now, json.dumps(keywords),
                ),
            )
            self._insert_fts(conn, note_id, subject, content, keywords)

        logger.debug("Stored exploration note %s: %s/%s", note_id, note_type, subject)
        return note_id

    def note_relationship(
        self,
        from_table: str,
        from_column: str,
        to_table: str,
        to_column: str,
        relationship_type: str = "inferred",
        notes: str = "",
    ) -> str:
        """Store a discovered table relationship."""
        subject = f"{from_table}.{from_column} -> {to_table}.{to_column}"
        content = (
            f"JOIN: {from_table}.{from_column} → {to_table}.{to_column} "
            f"(type: {relationship_type}). {notes}"
        )
        structured = {
            "from_table": from_table,
            "from_column": from_column,
            "to_table": to_table,
            "to_column": to_column,
            "relationship_type": relationship_type,
        }
        return self.note(
            note_type="relationship",
            subject=subject,
            content=content,
            structured_data=structured,
            confidence=0.8,
        )

    def note_query_path(
        self,
        question_pattern: str,
        steps: list[str],
        final_sql: str = "",
    ) -> str:
        """Store a multi-step query recipe."""
        content = f"Recipe for: {question_pattern}\n"
        for i, step in enumerate(steps, 1):
            content += f"  Step {i}: {step}\n"
        if final_sql:
            content += f"Final SQL: {final_sql[:500]}"
        structured = {
            "question_pattern": question_pattern,
            "steps": steps,
            "final_sql": final_sql,
        }
        return self.note(
            note_type="query_path",
            subject=question_pattern[:120],
            content=content,
            structured_data=structured,
            confidence=0.8,
        )

    # ------------------------------------------------------------------
    # Auto-extraction helpers (called by the loop passively)
    # ------------------------------------------------------------------

    def auto_note_table_profile(self, tool_result: dict[str, Any], table_name: str = "") -> None:
        """Extract table profile from explore_table result."""
        table = table_name or tool_result.get("table_name", tool_result.get("name", ""))
        if not table:
            return
        columns = tool_result.get("columns", [])
        row_count = tool_result.get("row_count", tool_result.get("total_rows", "unknown"))
        col_names = [c.get("name", c) if isinstance(c, dict) else str(c) for c in columns[:30]]
        content = f"{table}: ~{row_count} rows. Columns: {', '.join(col_names)}"
        if isinstance(row_count, (int, float)) and row_count > 10_000_000:
            content += "\n⚠️ Large table — use exact match only, never ILIKE or leading-% wildcards."
        self.note(
            note_type="table_profile",
            subject=table,
            content=content,
            structured_data={"row_count": row_count, "columns": col_names},
            confidence=0.85,
        )

    def auto_note_row_count(self, tool_result: dict[str, Any]) -> None:
        """Auto-note when we discover a large table via count_estimate."""
        count = tool_result.get("count", 0)
        table = tool_result.get("table", "")
        if not table or not isinstance(count, (int, float)):
            return
        if count > 10_000_000:
            self.note(
                note_type="table_profile",
                subject=table,
                content=(
                    f"{table}: ~{count:,.0f} rows. Large table — "
                    "use exact match (=) only, never ILIKE or leading-% wildcards."
                ),
                structured_data={"row_count": int(count)},
                confidence=0.9,
            )

    def auto_note_safety_warning(self, table_name: str, error_msg: str, sql: str = "") -> None:
        """Auto-note when a query times out or fails on a table."""
        content = f"Query issue on {table_name}: {error_msg[:300]}"
        if sql:
            content += f"\nFailed SQL: {sql[:200]}"
        self.note(
            note_type="safety_warning",
            subject=table_name,
            content=content,
            confidence=0.85,
        )

    def auto_note_query_path(
        self,
        question: str,
        query_log: list[dict[str, Any]],
        final_sql: str,
    ) -> None:
        """Auto-extract a query path from a multi-iteration session."""
        steps = []
        for entry in query_log:
            tool = entry.get("tool", "")
            if tool == "explore_table":
                steps.append(f"Explored table {entry.get('table', '?')}")
            elif tool == "search_schema":
                steps.append(f"Searched schema for '{entry.get('keywords', '?')}'")
            elif tool == "count_estimate":
                steps.append(f"Counted {entry.get('table', '?')}: {entry.get('count', '?')} rows")
            elif entry.get("sql") and not entry.get("blocked") and not entry.get("error"):
                steps.append(f"Ran SQL: {entry['sql'][:120]}")
        if steps and final_sql:
            self.note_query_path(
                question_pattern=question[:120],
                steps=steps[-8:],  # Keep last 8 steps
                final_sql=final_sql,
            )

    def note_routing_outcome(
        self,
        question: str,
        datasource: str,
        success: bool,
        iterations_used: int = 0,
    ) -> None:
        """Record which datasource answered a question type."""
        from querybridge.memory.persistent import _tokenize
        keywords = _tokenize(question)
        # Derive a short "question type" from keywords
        q_type = " ".join(keywords[:5]) if keywords else "general"

        content = (
            f"Question pattern '{q_type}' → {'answered by' if success else 'failed on'} "
            f"{datasource} ({iterations_used} iterations)."
        )
        structured = {
            "question_keywords": keywords[:10],
            "datasource": datasource,
            "success": success,
            "iterations_used": iterations_used,
        }
        self.note(
            note_type="routing_outcome",
            subject=f"routing:{q_type}:{datasource}",
            content=content,
            structured_data=structured,
            confidence=0.75 if success else 0.5,
        )

    # ------------------------------------------------------------------
    # Recall — search for relevant notes
    # ------------------------------------------------------------------

    def recall(
        self,
        topic: str,
        datasource: str | None = None,
        note_types: list[str] | None = None,
        limit: int = 10,
    ) -> list[ExplorationNote]:
        """Recall exploration notes relevant to a topic.

        Uses FTS5 when available, falls back to keyword LIKE search.
        Returns notes ranked by relevance × recency × usage.
        """
        ds = datasource or self._datasource
        results = self._recall_fts(topic, ds, note_types, limit * 3)
        if not results:
            results = self._recall_keywords(topic, ds, note_types, limit * 3)

        # Rank by composite score: relevance is already baked in from search,
        # boost by recency and usage
        now = time.time()
        scored: list[tuple[float, ExplorationNote]] = []
        for note in results:
            age_days = (now - note.last_used_at) / 86400
            recency_boost = max(0.1, 1.0 - (age_days / 60))  # Decays over 60 days
            usage_boost = 1.0 + min(note.times_used, 10) * 0.05
            score = note.confidence * recency_boost * usage_boost
            scored.append((score, note))

        scored.sort(key=lambda x: x[0], reverse=True)
        top = [note for _, note in scored[:limit]]

        # Update last_used_at for recalled notes
        if top:
            self._mark_used([n.id for n in top])

        return top

    def recall_routing(
        self,
        question: str,
        limit: int = 5,
    ) -> list[ExplorationNote]:
        """Recall routing outcome notes across ALL datasources for a question.

        Used by the router before routing to inject learned preferences.
        """
        results = self._recall_keywords(
            topic=question,
            datasource=None,  # Search all datasources
            note_types=["routing_outcome"],
            limit=limit,
        )
        if results:
            self._mark_used([n.id for n in results])
        return results

    def _recall_fts(
        self,
        topic: str,
        datasource: str,
        note_types: list[str] | None,
        limit: int,
    ) -> list[ExplorationNote]:
        """FTS5-based recall."""
        keywords = _extract_keywords(topic)
        if not keywords:
            return []
        fts_query = " OR ".join(keywords[:8])
        try:
            with self._connect() as conn:
                # Check if FTS table exists
                conn.execute("SELECT 1 FROM exploration_notes_fts LIMIT 1")

                rows = conn.execute(
                    """SELECT n.* FROM exploration_notes n
                       JOIN exploration_notes_fts f ON n.rowid = f.rowid
                       WHERE exploration_notes_fts MATCH ?
                         AND n.datasource = ?
                       LIMIT ?""",
                    (fts_query, datasource, limit),
                ).fetchall()

                if note_types:
                    rows = [r for r in rows if r["note_type"] in note_types]

                return [self._row_to_note(r) for r in rows]
        except sqlite3.OperationalError:
            return []

    def _recall_keywords(
        self,
        topic: str,
        datasource: str | None,
        note_types: list[str] | None,
        limit: int,
    ) -> list[ExplorationNote]:
        """Keyword LIKE fallback recall."""
        keywords = _extract_keywords(topic)
        if not keywords:
            return []

        with self._connect() as conn:
            # Build query
            conditions = ["confidence > 0.2"]
            params: list[Any] = []

            if datasource:
                conditions.append("datasource = ?")
                params.append(datasource)

            if note_types:
                placeholders = ",".join("?" for _ in note_types)
                conditions.append(f"note_type IN ({placeholders})")
                params.extend(note_types)

            # Match any keyword in subject, content, or keywords JSON
            kw_clauses = []
            for kw in keywords[:6]:
                kw_clauses.append("(subject LIKE ? OR content LIKE ? OR keywords LIKE ?)")
                params.extend([f"%{kw}%", f"%{kw}%", f"%{kw}%"])

            if kw_clauses:
                conditions.append(f"({' OR '.join(kw_clauses)})")

            where = " AND ".join(conditions)
            rows = conn.execute(
                f"SELECT * FROM exploration_notes WHERE {where} "
                f"ORDER BY last_used_at DESC LIMIT ?",
                params + [limit],
            ).fetchall()

            return [self._row_to_note(r) for r in rows]

    def _mark_used(self, note_ids: list[str]) -> None:
        """Update last_used_at and times_used for recalled notes."""
        now = time.time()
        with self._connect() as conn:
            for nid in note_ids:
                conn.execute(
                    "UPDATE exploration_notes "
                    "SET last_used_at = ?, times_used = times_used + 1 "
                    "WHERE id = ?",
                    (now, nid),
                )

    # ------------------------------------------------------------------
    # Lifecycle: boost / decay / prune
    # ------------------------------------------------------------------

    def boost(self, note_id: str) -> None:
        """Increase confidence when a recalled note led to success."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE exploration_notes "
                "SET confidence = MIN(1.0, confidence + 0.1) WHERE id = ?",
                (note_id,),
            )

    def decay(self, note_id: str) -> None:
        """Decrease confidence when a recalled note led to failure."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE exploration_notes "
                "SET confidence = MAX(0.0, confidence - 0.2) WHERE id = ?",
                (note_id,),
            )

    def prune_stale(self, max_age_days: int = 30, min_confidence: float = 0.2) -> int:
        """Remove notes that are old+unused or have low confidence."""
        cutoff = time.time() - (max_age_days * 86400)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM exploration_notes WHERE "
                "confidence < ? OR (last_used_at < ? AND times_used = 0)",
                (min_confidence, cutoff),
            )
            deleted = cursor.rowcount
            if deleted:
                logger.info("Pruned %d stale exploration notes", deleted)
            return deleted

    # ------------------------------------------------------------------
    # Formatting for LLM prompt injection
    # ------------------------------------------------------------------

    def format_for_prompt(self, notes: list[ExplorationNote]) -> str:
        """Render notes as markdown for system prompt injection."""
        if not notes:
            return ""

        sections: dict[str, list[str]] = {}
        for n in notes:
            sections.setdefault(n.note_type, []).append(
                f"- **{n.subject}**: {n.content}"
            )

        lines = ["## Your Previous Exploration Notes\n"]
        type_labels = {
            "table_profile": "Table Profiles",
            "column_relevance": "Column Relevance",
            "relationship": "Discovered Relationships",
            "query_path": "Query Recipes",
            "schema_map": "Schema Topology",
            "routing_outcome": "Routing History",
            "safety_warning": "Safety Warnings",
            "negative_knowledge": "What Didn't Work",
        }
        for ntype, items in sections.items():
            label = type_labels.get(ntype, ntype.replace("_", " ").title())
            lines.append(f"### {label}")
            lines.extend(items[:5])  # Cap at 5 per type to limit prompt size
            lines.append("")

        return "\n".join(lines)

    def format_routing_context(self, notes: list[ExplorationNote]) -> str:
        """Format routing notes for the router prompt."""
        if not notes:
            return ""
        lines = ["Past routing experience:"]
        for n in notes:
            lines.append(f"- {n.content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return stats about stored notes."""
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM exploration_notes WHERE datasource = ?",
                (self._datasource,),
            ).fetchone()[0]
            by_type = conn.execute(
                "SELECT note_type, COUNT(*) as cnt FROM exploration_notes "
                "WHERE datasource = ? GROUP BY note_type ORDER BY cnt DESC",
                (self._datasource,),
            ).fetchall()
        return {
            "total_notes": total,
            "by_type": {r["note_type"]: r["cnt"] for r in by_type},
            "datasource": self._datasource,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_note(row: sqlite3.Row) -> ExplorationNote:
        """Convert a DB row to ExplorationNote."""
        return ExplorationNote(
            id=row["id"],
            datasource=row["datasource"],
            note_type=row["note_type"],
            subject=row["subject"],
            content=row["content"],
            structured_data=json.loads(row["structured_data"] or "{}"),
            confidence=row["confidence"],
            source_question=row["source_question"] or "",
            created_at=row["created_at"],
            last_used_at=row["last_used_at"],
            times_used=row["times_used"],
            keywords=json.loads(row["keywords"] or "[]"),
        )

    def _insert_fts(self, conn: sqlite3.Connection, note_id: str,
                    subject: str, content: str, keywords: list[str]) -> None:
        """Insert into FTS5 table."""
        try:
            conn.execute(
                "INSERT INTO exploration_notes_fts(rowid, subject, content, keywords) "
                "VALUES ((SELECT rowid FROM exploration_notes WHERE id = ?), ?, ?, ?)",
                (note_id, subject, content, " ".join(keywords)),
            )
        except sqlite3.OperationalError:
            pass  # FTS5 not available

    def _update_fts(self, conn: sqlite3.Connection, note_id: str,
                    subject: str, content: str, keywords: list[str]) -> None:
        """Update FTS5 entry for an existing note."""
        try:
            # Delete old FTS entry then re-insert
            conn.execute(
                "DELETE FROM exploration_notes_fts WHERE rowid = "
                "(SELECT rowid FROM exploration_notes WHERE id = ?)",
                (note_id,),
            )
            self._insert_fts(conn, note_id, subject, content, keywords)
        except sqlite3.OperationalError:
            pass
