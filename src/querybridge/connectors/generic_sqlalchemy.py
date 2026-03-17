"""Generic SQLAlchemy connector — fallback for any supported dialect."""

from __future__ import annotations

import re
import time
import logging
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text, inspect as sa_inspect

from querybridge.connectors.base import DatabaseConnector, QueryResult
from querybridge.core.models import ColumnInfo, Relationship, TableInfo, ValueCount

logger = logging.getLogger("querybridge.connectors.generic")

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    if not name or not _SAFE_IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


class GenericSQLAlchemyConnector(DatabaseConnector):
    """Fallback connector using SQLAlchemy — works with any supported dialect."""

    def __init__(self, connection_url: str, read_only: bool = True, pool_size: int = 3):
        self._read_only = read_only
        self._engine = create_async_engine(
            connection_url,
            pool_size=pool_size,
            max_overflow=2,
            pool_timeout=10,
            pool_pre_ping=True,
            execution_options={"postgresql_readonly": True} if read_only else {},
        )
        self._session_factory = sessionmaker(
            self._engine, class_=AsyncSession, expire_on_commit=False
        )

    async def execute(self, sql: str, max_rows: int = 500) -> QueryResult:
        start = time.monotonic()
        async with self._session_factory() as session:
            if self._read_only:
                await session.execute(text("SET TRANSACTION READ ONLY"))
            result = await session.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]
            elapsed = int((time.monotonic() - start) * 1000)
            row_dicts = []
            for row in rows:
                d = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, bytes):
                        val = val.hex()
                    d[col] = val
                row_dicts.append(d)
            return QueryResult(columns=columns, rows=row_dicts,
                               row_count=len(row_dicts), truncated=truncated,
                               execution_time_ms=elapsed)

    async def get_tables(self) -> List[TableInfo]:
        result = await self.execute(
            "SELECT table_name AS name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema NOT IN ('information_schema', 'pg_catalog') "
            "ORDER BY table_name"
        )
        return [TableInfo(name=r["name"], table_type=r["table_type"].lower()) for r in result.rows]

    async def get_columns(self, table: str) -> List[ColumnInfo]:
        table = _validate_identifier(table)
        result = await self.execute(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_name = '{table}' "
            f"ORDER BY ordinal_position"
        )
        return [
            ColumnInfo(name=r["column_name"], data_type=r["data_type"],
                       nullable=r["is_nullable"] == "YES")
            for r in result.rows
        ]

    async def get_distinct_values(self, table: str, column: str, limit: int = 25) -> List[ValueCount]:
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        result = await self.execute(
            f'SELECT CAST("{column}" AS VARCHAR) AS value, COUNT(*) AS count '
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
        try:
            result = await self.execute("""
                SELECT kcu.table_name AS from_table, kcu.column_name AS from_column,
                       ccu.table_name AS to_table, ccu.column_name AS to_column
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
                JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
            """)
            return [
                Relationship(from_table=r["from_table"], from_column=r["from_column"],
                             to_table=r["to_table"], to_column=r["to_column"])
                for r in result.rows
            ]
        except Exception:
            return []

    def get_dialect_name(self) -> str:
        return "generic"

    async def close(self):
        await self._engine.dispose()
