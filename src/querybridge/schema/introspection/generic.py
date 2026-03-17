"""Generic ANSI SQL schema introspection queries."""

TABLES_QUERY = """
SELECT table_name,
       LOWER(table_type) AS table_type
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_name
"""

COLUMNS_QUERY = """
SELECT column_name, data_type,
       CASE WHEN is_nullable = 'YES' THEN TRUE ELSE FALSE END AS nullable
FROM information_schema.columns
WHERE table_name = :table_name
ORDER BY ordinal_position
"""
