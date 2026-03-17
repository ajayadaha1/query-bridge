"""PostgreSQL-specific schema introspection queries."""

# Full table + column introspection via pg_catalog
TABLES_QUERY = """
SELECT c.relname AS table_name,
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
"""

COLUMNS_QUERY = """
SELECT a.attname AS column_name,
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
  AND c.relname = :table_name
  AND a.attnum > 0
  AND NOT a.attisdropped
ORDER BY a.attnum
"""

FOREIGN_KEYS_QUERY = """
SELECT kcu.table_name AS from_table,
       kcu.column_name AS from_column,
       ccu.table_name AS to_table,
       ccu.column_name AS to_column
FROM information_schema.table_constraints tc
JOIN information_schema.key_column_usage kcu ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage ccu ON tc.constraint_name = ccu.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
"""

ROW_COUNTS_QUERY = """
SELECT relname AS table_name, n_live_tup AS row_count
FROM pg_stat_user_tables
ORDER BY n_live_tup DESC
"""

JSONB_COLUMNS_QUERY = """
SELECT table_name, column_name, data_type
FROM information_schema.columns
WHERE table_schema = 'public'
  AND data_type IN ('json', 'jsonb')
ORDER BY table_name, column_name
"""
