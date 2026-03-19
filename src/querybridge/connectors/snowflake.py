"""Snowflake connector — wraps sync SQLAlchemy in asyncio.to_thread.

The Snowflake dialect doesn't provide an async driver, so every blocking
call is offloaded to a thread via ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from querybridge.connectors.base import DatabaseConnector, QueryResult
from querybridge.core.models import ColumnInfo, Relationship, TableInfo, ValueCount

logger = logging.getLogger("querybridge.connectors.snowflake")

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_.]*$")


def _validate_identifier(name: str) -> str:
    if not name or not _SAFE_IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


def _load_private_key_der(key_path: str) -> bytes:
    """Load a PEM/P8 private key file and return DER-encoded bytes."""
    from cryptography.hazmat.primitives import serialization

    with open(key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _strip_private_key_from_url(url: str) -> tuple[str, str | None]:
    """Remove private_key_path from the URL and return (clean_url, key_path)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    key_path = params.pop("private_key_path", [None])[0]
    # Rebuild query string without private_key_path
    clean_parts = []
    for k, vals in params.items():
        for v in vals:
            clean_parts.append(f"{k}={v}")
    clean_query = "&".join(clean_parts)
    clean_url = parsed._replace(query=clean_query).geturl()
    return clean_url, key_path


class SnowflakeConnector(DatabaseConnector):
    """Sync Snowflake connector wrapped for async usage."""

    def __init__(self, connection_url: str, read_only: bool = True, pool_size: int = 5):
        self._read_only = read_only

        # Extract and handle private_key_path from URL
        clean_url, key_path = _strip_private_key_from_url(connection_url)
        connect_args: dict[str, Any] = {}
        if key_path:
            try:
                connect_args["private_key"] = _load_private_key_der(key_path)
                logger.info("Loaded Snowflake private key from %s", key_path)
            except Exception as e:
                logger.error("Failed to load Snowflake private key from %s: %s", key_path, e)
                raise

        self._engine = create_engine(
            clean_url,
            pool_size=pool_size,
            max_overflow=5,
            pool_timeout=60,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._session_factory = sessionmaker(bind=self._engine, expire_on_commit=False)

    def _execute_sync(self, sql: str, max_rows: int = 500) -> QueryResult:
        start = time.monotonic()
        with self._session_factory() as session:
            result = session.execute(text(sql))
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
            return QueryResult(
                columns=columns, rows=row_dicts,
                row_count=len(row_dicts), truncated=truncated,
                execution_time_ms=elapsed,
            )

    async def execute(self, sql: str, max_rows: int = 500) -> QueryResult:
        return await asyncio.to_thread(self._execute_sync, sql, max_rows)

    async def get_tables(self) -> list[TableInfo]:
        result = await self.execute(
            "SELECT table_name AS name, table_type "
            "FROM information_schema.tables "
            "WHERE table_schema = CURRENT_SCHEMA() "
            "ORDER BY table_name"
        )
        return [TableInfo(name=r["name"], table_type=r["table_type"].lower()) for r in result.rows]

    async def get_columns(self, table: str) -> list[ColumnInfo]:
        table = _validate_identifier(table)
        result = await self.execute(
            f"SELECT column_name, data_type, is_nullable "
            f"FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND table_schema = CURRENT_SCHEMA() "
            f"ORDER BY ordinal_position"
        )
        return [
            ColumnInfo(name=r["column_name"], data_type=r["data_type"],
                       nullable=r["is_nullable"] == "YES")
            for r in result.rows
        ]

    async def get_distinct_values(self, table: str, column: str, limit: int = 25) -> list[ValueCount]:
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        result = await self.execute(
            f'SELECT CAST("{column}" AS VARCHAR) AS value, COUNT(*) AS count '
            f'FROM {table} WHERE "{column}" IS NOT NULL '
            f"GROUP BY 1 ORDER BY 2 DESC LIMIT {min(limit, 50)}"
        )
        return [ValueCount(value=r["value"], count=r["count"]) for r in result.rows]

    async def get_row_count(self, table: str, where: str | None = None) -> int:
        table = _validate_identifier(table)
        sql = f"SELECT COUNT(*) AS cnt FROM {table}"
        if where:
            sql += f" WHERE {where}"
        result = await self.execute(sql)
        return result.rows[0]["cnt"] if result.rows else 0

    async def get_sample_rows(self, table: str, limit: int = 3) -> list[dict[str, Any]]:
        table = _validate_identifier(table)
        result = await self.execute(f"SELECT * FROM {table} LIMIT {limit}")
        return result.rows

    async def get_relationships(self) -> list[Relationship]:
        try:
            result = await self.execute("""
                SELECT fk.table_name AS from_table, fk.column_name AS from_column,
                       pk.table_name AS to_table, pk.column_name AS to_column
                FROM information_schema.referential_constraints rc
                JOIN information_schema.key_column_usage fk
                    ON rc.constraint_name = fk.constraint_name
                JOIN information_schema.key_column_usage pk
                    ON rc.unique_constraint_name = pk.constraint_name
                WHERE fk.table_schema = CURRENT_SCHEMA()
            """)
            return [
                Relationship(from_table=r["from_table"], from_column=r["from_column"],
                             to_table=r["to_table"], to_column=r["to_column"])
                for r in result.rows
            ]
        except Exception:
            return []

    def get_dialect_name(self) -> str:
        return "snowflake"

    async def close(self):
        await asyncio.to_thread(self._engine.dispose)
