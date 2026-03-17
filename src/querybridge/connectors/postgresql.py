"""PostgreSQL connector using SQLAlchemy async + asyncpg."""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from querybridge.connectors.base import DatabaseConnector, QueryResult
from querybridge.core.models import ColumnInfo, Relationship, TableInfo, ValueCount

logger = logging.getLogger("querybridge.connectors.postgresql")

_SAFE_IDENT = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


def _validate_identifier(name: str) -> str:
    if not name or not _SAFE_IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


class PostgreSQLConnector(DatabaseConnector):
    """PostgreSQL via asyncpg + SQLAlchemy async."""

    def __init__(
        self,
        connection_url: str,
        read_only: bool = True,
        statement_timeout_ms: int = 10_000,
        pool_size: int = 3,
    ):
        connect_args: dict[str, Any] = {}
        if read_only:
            connect_args["server_settings"] = {
                "default_transaction_read_only": "on",
                "statement_timeout": str(statement_timeout_ms),
            }

        # Normalize URL scheme
        url = connection_url
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        elif not url.startswith("postgresql+asyncpg://"):
            url = f"postgresql+asyncpg://{url}"

        self._engine = create_async_engine(
            url,
            pool_size=pool_size,
            max_overflow=2,
            pool_timeout=10,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        self._session_factory = sessionmaker(
            bind=self._engine, class_=AsyncSession, expire_on_commit=False  # type: ignore[call-overload]
        )

    async def execute(self, sql: str, max_rows: int = 500) -> QueryResult:
        start = time.monotonic()
        async with self._session_factory() as session:
            result = await session.execute(text(sql))
            columns = list(result.keys())
            rows = result.fetchmany(max_rows + 1)

            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]

            elapsed_ms = int((time.monotonic() - start) * 1000)

            row_dicts = []
            for row in rows:
                row_dict = {}
                for i, col in enumerate(columns):
                    val = row[i]
                    if hasattr(val, "isoformat"):
                        val = val.isoformat()
                    elif isinstance(val, bytes):
                        val = val.hex()
                    elif isinstance(val, set):
                        val = list(val)
                    row_dict[col] = val
                row_dicts.append(row_dict)

            return QueryResult(
                columns=columns,
                rows=row_dicts,
                row_count=len(row_dicts),
                truncated=truncated,
                execution_time_ms=elapsed_ms,
            )

    async def get_tables(self) -> list[TableInfo]:
        result = await self.execute("""
            SELECT c.relname AS name,
                   CASE c.relkind
                       WHEN 'r' THEN 'table'
                       WHEN 'v' THEN 'view'
                       WHEN 'm' THEN 'materialized_view'
                   END AS table_type,
                   COALESCE(s.n_live_tup, 0) AS row_count_estimate
            FROM pg_class c
            JOIN pg_namespace n ON c.relnamespace = n.oid
            LEFT JOIN pg_stat_user_tables s ON s.relname = c.relname
            WHERE n.nspname = 'public'
              AND c.relkind IN ('r', 'v', 'm')
            ORDER BY c.relname
        """)
        return [
            TableInfo(
                name=row["name"],
                table_type=row["table_type"],
                row_count_estimate=row["row_count_estimate"] or 0,
            )
            for row in result.rows
        ]

    async def get_columns(self, table: str) -> list[ColumnInfo]:
        table = _validate_identifier(table)
        result = await self.execute(f"""
            SELECT a.attname AS name,
                   pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                   NOT a.attnotnull AS nullable,
                   COALESCE(
                       (SELECT TRUE FROM pg_index i
                        WHERE i.indrelid = a.attrelid AND a.attnum = ANY(i.indkey) AND i.indisprimary),
                       FALSE
                   ) AS is_pk,
                   pg_catalog.col_description(a.attrelid, a.attnum) AS comment
            FROM pg_attribute a
            JOIN pg_class c ON a.attrelid = c.oid
            JOIN pg_namespace n ON c.relnamespace = n.oid
            WHERE n.nspname = 'public'
              AND c.relname = '{table}'
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
        """)
        return [
            ColumnInfo(
                name=row["name"],
                data_type=row["data_type"],
                nullable=row["nullable"],
                is_pk=row["is_pk"],
                comment=row.get("comment"),
            )
            for row in result.rows
        ]

    async def get_distinct_values(
        self, table: str, column: str, limit: int = 25
    ) -> list[ValueCount]:
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        limit = min(max(1, int(limit)), 50)
        result = await self.execute(
            f'SELECT "{column}"::text AS value, COUNT(*) AS count '
            f"FROM {table} "
            f'WHERE "{column}" IS NOT NULL '
            f"GROUP BY 1 ORDER BY 2 DESC LIMIT {limit}"
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
        result = await self.execute("""
            SELECT
                kcu.table_name AS from_table,
                kcu.column_name AS from_column,
                ccu.table_name AS to_table,
                ccu.column_name AS to_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage ccu
                ON tc.constraint_name = ccu.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
        """)
        return [
            Relationship(
                from_table=row["from_table"],
                from_column=row["from_column"],
                to_table=row["to_table"],
                to_column=row["to_column"],
                relationship_type="foreign_key",
                confidence=1.0,
                join_hint=(
                    f"LEFT JOIN {row['to_table']} ON "
                    f"{row['from_table']}.{row['from_column']} = "
                    f"{row['to_table']}.{row['to_column']}"
                ),
            )
            for row in result.rows
        ]

    def get_dialect_name(self) -> str:
        return "postgresql"

    async def close(self):
        await self._engine.dispose()

    # PostgreSQL-specific exploration tools

    async def explore_jsonb(
        self, table: str, column: str, path: str = ""
    ) -> dict[str, Any]:
        """Explore JSONB structure at any depth."""
        table = _validate_identifier(table)
        column = _validate_identifier(column)

        # Check if column is json vs jsonb
        col_type_result = await self.execute(
            f"SELECT data_type FROM information_schema.columns "
            f"WHERE table_schema = 'public' AND table_name = '{table}' "
            f"AND column_name = '{column}'"
        )
        needs_cast = bool(
            col_type_result.rows
            and col_type_result.rows[0]["data_type"] == "json"
        )

        accessor = f"{column}::jsonb" if needs_cast else column
        if path:
            for part in path.split("."):
                if "'" in part or ";" in part or "--" in part:
                    raise ValueError(f"Invalid JSONB path segment: {part!r}")
                accessor += f"->'{part}'"

        try:
            keys_result = await self.execute(
                f"SELECT key, COUNT(*) AS frequency "
                f"FROM {table}, jsonb_object_keys({accessor}) AS key "
                f"GROUP BY key ORDER BY frequency DESC LIMIT 30"
            )
            return {
                "table": table, "column": column,
                "path": path or "(root)", "type": "object",
                "keys": [
                    {"key": r["key"], "frequency": r["frequency"]}
                    for r in keys_result.rows
                ],
            }
        except Exception:
            vals = await self.execute(
                f"SELECT ({accessor})::text AS value, COUNT(*) AS count "
                f"FROM {table} WHERE ({accessor}) IS NOT NULL "
                f"GROUP BY 1 ORDER BY 2 DESC LIMIT 20"
            )
            return {
                "table": table, "column": column,
                "path": path or "(root)", "type": "scalar_or_array",
                "distinct_values": vals.rows,
            }

    async def search_text(
        self, table: str, column: str, term: str, limit: int = 50
    ) -> dict[str, Any]:
        """Full-text ILIKE search on a text/jsonb column."""
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        clean = term.strip().replace("'", "''").replace(";", "").replace("--", "")
        if not clean or len(clean) < 2:
            return {"error": "Search term must be at least 2 characters"}

        count_result = await self.execute(
            f"SELECT COUNT(*) AS cnt FROM {table} "
            f"WHERE {column}::text ILIKE '%{clean}%'"
        )
        total = count_result.rows[0]["cnt"] if count_result.rows else 0

        result = await self.execute(
            f"SELECT * FROM {table} "
            f"WHERE {column}::text ILIKE '%{clean}%' LIMIT {min(limit, 50)}"
        )
        return {
            "search_term": term,
            "total_matches": total,
            "rows": result.rows,
        }

    async def validate_filter_values(
        self, table: str, column: str, values: list[str]
    ) -> dict[str, Any]:
        """Check if specific values exist in a column with fuzzy matching."""
        table = _validate_identifier(table)
        column = _validate_identifier(column)
        values = values[:10]

        # Check pg_trgm availability
        try:
            trgm = await self.execute(
                "SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm'"
            )
            has_trgm = bool(trgm.rows)
        except Exception:
            has_trgm = False

        results = {}
        for value in values:
            clean = str(value).strip().replace("'", "''")
            if not clean or len(clean) > 200:
                results[value] = {"found": False, "exact": False, "matches": [], "count": 0}
                continue

            exact = await self.execute(
                f'SELECT "{column}", COUNT(*) AS cnt '
                f"FROM {table} WHERE \"{column}\" = '{clean}' "
                f'GROUP BY "{column}"'
            )
            if exact.rows:
                results[value] = {
                    "found": True, "exact": True,
                    "matches": [{"value": value, "count": exact.rows[0]["cnt"], "similarity": 1.0}],
                    "count": exact.rows[0]["cnt"],
                }
                continue

            if has_trgm:
                fuzzy = await self.execute(
                    f'SELECT DISTINCT "{column}"::text AS value, '
                    f"COUNT(*) OVER (PARTITION BY \"{column}\") AS cnt, "
                    f"similarity(\"{column}\"::text, '{clean}') AS sim "
                    f"FROM {table} WHERE \"{column}\" IS NOT NULL "
                    f"AND similarity(\"{column}\"::text, '{clean}') > 0.2 "
                    f"ORDER BY sim DESC LIMIT 10"
                )
            else:
                fuzzy = await self.execute(
                    f'SELECT "{column}"::text AS value, COUNT(*) AS cnt '
                    f"FROM {table} WHERE \"{column}\"::text ILIKE '%{clean}%' "
                    f'GROUP BY "{column}" ORDER BY cnt DESC LIMIT 10'
                )

            if fuzzy.rows:
                matches = [
                    {"value": r["value"], "count": r["cnt"], "similarity": r.get("sim", 0.5)}
                    for r in fuzzy.rows
                ]
                results[value] = {
                    "found": True, "exact": False,
                    "matches": matches,
                    "count": sum(m["count"] for m in matches),
                }
            else:
                results[value] = {"found": False, "exact": False, "matches": [], "count": 0}

        return {"table": table, "column": column, "results": results, "has_trigram": has_trgm}

    async def cross_validate(
        self, primary_sql: str, check_sql: str, note: str = ""
    ) -> dict[str, Any]:
        """Run two queries and compare for consistency."""
        primary = await self.execute(primary_sql, max_rows=50)
        check = await self.execute(check_sql, max_rows=50)

        p_count = primary.row_count
        c_count = check.row_count
        consistent = abs(p_count - c_count) <= max(p_count, c_count) * 0.2 if max(p_count, c_count) > 0 else True

        return {
            "primary_result": primary.to_dict(),
            "check_result": check.to_dict(),
            "consistent": consistent,
            "note": note,
        }
