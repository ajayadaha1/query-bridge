# Safety

QueryBridge is designed to be safe by default.

## SQLGuard

Every SQL query is validated before execution:

- **Allowlist**: Only `SELECT` and `WITH` (CTE) queries pass
- **Blocklist**: `DROP`, `DELETE`, `INSERT`, `UPDATE`, `ALTER`, `TRUNCATE`, `GRANT`, `REVOKE`
- **Dialect-specific**: PostgreSQL blocks `COPY`, `pg_`, `lo_`; SQLite blocks `ATTACH`, `DETACH`, `PRAGMA` (write)
- **Pattern matching**: Detects `; DROP`, comment injection, stacked queries
- **Length limit**: Configurable maximum query length

## ResultValidator

After query execution, results are checked for:

- **Zero rows**: Flags when a query returns no data
- **Too many rows**: Detects JOIN explosions
- **High NULL rate**: Warns when > 50% of a column is NULL
- **Duplicate queries**: Detects repeated identical approaches
- **Single-value anomalies**: Flags suspiciously uniform results

## Input Sanitization

User input is sanitized before any processing:

- HTML/script tag removal
- SQL identifier validation
- Value sanitization for safe interpolation
