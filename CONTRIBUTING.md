# Contributing to QueryBridge

Thank you for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/ajayadaha1/query-bridge
cd query-bridge
make dev        # installs with dev dependencies + pre-commit hooks
make test       # run tests
make lint       # run linter
```

## How to Contribute

### Bug Reports
- Use the [bug report template](https://github.com/ajayadaha1/query-bridge/issues/new?template=bug_report.md)
- Include a minimal reproduction example
- Mention your Python version, database, and LLM provider

### Feature Requests
- Use the [feature request template](https://github.com/ajayadaha1/query-bridge/issues/new?template=feature_request.md)
- Explain the use case, not just the feature

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Ensure tests pass: `make test`
5. Ensure lint passes: `make lint`
6. Commit with a descriptive message
7. Push and open a PR

### Code Style

- We use [Ruff](https://github.com/astral-sh/ruff) for linting and formatting
- Run `make format` to auto-format
- Line length: 120 characters
- Type hints on all public functions
- Docstrings on all public classes and methods

### Writing Plugins

One of the best ways to contribute is to write domain plugins! See the [plugin documentation](https://github.com/ajayadaha1/query-bridge/blob/main/docs/plugins/writing-plugins.md).

### Adding Database Connectors

New connectors should:
1. Subclass `DatabaseConnector` from `querybridge.connectors.base`
2. Implement all abstract methods
3. Add an optional dependency group in `pyproject.toml`
4. Add tests in `tests/`
5. Add documentation in `docs/`

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
