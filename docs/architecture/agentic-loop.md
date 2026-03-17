# Agentic Loop

The core of QueryBridge is a multi-step agentic loop where the LLM iteratively explores, queries, validates, and refines its approach.

## Phases

| Phase | Budget | Purpose |
|-------|--------|---------|
| **Explore** | 2 iterations | Discover schema, check filter values, understand data |
| **Execute** | 5 iterations | Write and run the main SQL query |
| **Validate** | 2 iterations | Cross-check results, verify row counts |
| **Refine** | Remaining | Fix anomalies, prepare final answer |

## Tools Available

The LLM can call these tools during the loop:

- `execute_sql` — Run a read-only SQL query
- `explore_table` — Get table structure and sample rows
- `get_distinct_values` — List unique values in a column
- `validate_filter_values` — Check if values exist in a column
- `column_profile` — Get column statistics (NULL rate, min/max, top values)
- `count_estimate` — Quick COUNT(*) with conditions
- `cross_validate` — Run two queries and compare results

## Safety

Every SQL query passes through `SQLGuard` before execution:

- Only SELECT/WITH queries allowed
- Blocked keywords (DROP, DELETE, INSERT, UPDATE, etc.)
- Dialect-specific blocks (COPY, ATTACH, etc.)
- Maximum query length enforcement
- Pattern-based injection detection
