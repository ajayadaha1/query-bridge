# Security Policy

## Supported Versions

| Version | Supported          |
|---------|--------------------|
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

**Do not open a public issue for security vulnerabilities.**

Instead, please email **ajayadaha1@github.com** with:

1. A description of the vulnerability
2. Steps to reproduce
3. Impact assessment
4. Suggested fix (if you have one)

We will acknowledge your report within 48 hours and aim to release a fix within 7 days for critical issues.

## Security Model

QueryBridge includes multiple layers of SQL safety:

- **SQL Guard**: Blocks destructive operations (DROP, DELETE, INSERT, UPDATE, TRUNCATE) by default
- **Read-only connections**: All database connections use read-only mode where supported
- **Query validation**: Results are validated before being returned
- **Input sanitization**: User inputs are sanitized before being passed to LLMs

See our [safety documentation](https://github.com/ajayadaha1/query-bridge/blob/main/docs/architecture/safety.md) for details.
