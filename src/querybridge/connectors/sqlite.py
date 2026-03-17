"""SQLite connector using aiosqlite."""

from __future__ import annotations

import re
import time
import logging
from typing import Any, Dict, List, Optional

from querybridge.connectors.base import DatabaseConnector, QueryResult
from querybridge.core.models import ColumnInfo, Relationship, TableInfo, ValueCount

logger = logging.getLogger("querybridge.connectors.sqlite")

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    if not name or not _SAFE_IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


class SQLiteConnector(DatabaseConnector):
    """SQLite via aiosqlite."""

    def __init__(self, database_path: str):
        import aiosqlite  # noqa: F401 — ensure available
        self._path = database_path
        self._db = None

    async def _get_db(self):
        if self._db is None:
            import aiosqlite
            self._db = await aiosqlite.connect(
                f"file:{self._path}?mode=ro", uri=True
            )
            self._db.row_factory = None
        return self._db

    async def execute(self, sql: str, max_rows: int = 500) -> QueryResult:
        db = await self._get_db()
        start = time.monotonic()
        cursor = await db.execute(sql)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows_raw = await cursor.fetchmany(max_rows + 1)
        truncated = len(rows_raw) > max_rows
        if truncated:
            rows_raw = rows_raw[:max_rows]
        elapsed = int((time.monotonic() - start) * 1000)
        row_dicts = [{columns[i]: row[i] for i in range(len(columns))} for row in rows_raw]
        return QueryResult(columns=columns, rows=row_dicts, row_count=len(row_dicts),
                           truncated=truncated, execution_time_ms=elapsed)

    async def get_tables(self) -> List[TableInfo]:
        result = await self.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table', 'view') ORDER BY name"
        )
        tables = []
        for row in result.rows:
            count_result = await self.execute(f"SELECT COUNT(*) AS cnt FROM [{row['name']}]")
            tables.append(TableInfo(
                name=row["name"],
                table_type=row["type"],
                row_count_estimate=count_result.rows[0]["cnt"] if count_result.rows else 0,
            ))
        return tables

    async def get_columns(self, table: str) -> List[ColumnInfo]:
        table = _validate_identifier(table)
        result = await self.execute(f"PRAGMA table_info({table})")
        return [
            ColumnInfo(
                name=row["name"], data_type=row["type"],
                nullable=not row["notnull"], is_pk=bool(row["pk"]),
            )
            for row in result.rows
        ]

    async def get_distinct_values(self, table: str, column: str, limit: int = 25) -> List[ValueCount]:
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        result = await self.execute(
            f'SELECT "{column}" AS value, COUNT(*) AS count '
            f'FROM {table} WHERE "{column}" IS NOT NULL '
            f"GROUP BY 1 ORDER BY 2 DESC LIMIT {min(limit, 50)}"
        )
        return [ValueCount(value=r["value"], count=r["count"]) for r in result.rows]

    async def get_row_count(self, table: str, where: Optional[str] = None) -> int:
        table = _validate_identifier(table)
        sql = f"SELECT COUNT(*) AS cnt FROM {table}"
        if where:
            sql += f" WHERE {where}"
        result = await self.execute(sql)
        return result.rows[0]["cnt"] if result.rows else 0

    async def get_sample_rows(self, table: str, limit: int = 3) -> List[Dict[str, Any]]:
        table = _validate_identifier(table)
        result = await self.execute(f"SELECT * FROM {table} LIMIT {limit}")
        return result.rows

    async def get_relationships(self) -> List[Relationship]:
        tables_result = await self.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
        relationships = []
        for trow in tables_result.rows:
            table = trow["name"]
            try:
                fk_result = await self.execute(f"PRAGMA foreign_key_list({table})")
                for fk in fk_result.rows:
                    relationships.append(Relationship(
                        from_table=table, from_column=fk["from"],
                        to_table=fk["table"], to_column=fk["to"],
                        relationship_type="foreign_key", confidence=1.0,
                    ))
            except Exception:
                pass
        return relationships

    def get_dialect_name(self) -> str:
        return "sqlite"

    async def close(self):
        if self._db:
            await self._db.close()
            self._db = None
