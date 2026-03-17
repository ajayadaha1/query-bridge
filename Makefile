.PHONY: help install dev test lint format typecheck clean docker-up docker-down docs docs-serve playground

PYTHON ?= python3
PIP ?= pip

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ─── Development ──────────────────────────────────────────────────────

install: ## Install querybridge (library only)
	$(PIP) install -e .

dev: ## Install with all dev dependencies
	$(PIP) install -e ".[dev,sqlite,server,export]"
	pre-commit install 2>/dev/null || true

test: ## Run tests
	pytest tests/ -v

test-cov: ## Run tests with coverage
	pytest tests/ -v --cov=querybridge --cov-report=term-missing --cov-report=html

lint: ## Run linter
	ruff check src/ tests/

format: ## Auto-format code
	ruff format src/ tests/
	ruff check --fix src/ tests/

typecheck: ## Run type checker
	mypy src/querybridge/

# ─── Docker ───────────────────────────────────────────────────────────

docker-up: ## Start full demo (API + Playground + Sample DB)
	docker compose up --build -d
	@echo ""
	@echo "  🚀 QueryBridge is running!"
	@echo ""
	@echo "  Playground:  http://localhost:3000"
	@echo "  API:         http://localhost:8000/docs"
	@echo "  Health:      http://localhost:8000/health"
	@echo ""

docker-down: ## Stop all containers
	docker compose down -v

docker-logs: ## Tail container logs
	docker compose logs -f

# ─── Docs ─────────────────────────────────────────────────────────────

docs: ## Build documentation
	mkdocs build -f docs/mkdocs.yml

docs-serve: ## Serve documentation locally
	mkdocs serve -f docs/mkdocs.yml

# ─── Demo ─────────────────────────────────────────────────────────────

demo: ## Run quick demo with bundled SQLite database
	@echo "Running QueryBridge demo with Chinook sample database..."
	$(PYTHON) examples/quickstart.py

demo-interactive: ## Start interactive REPL with sample DB
	querybridge --dsn "sqlite:///demo/chinook.db" --provider openai interactive

# ─── Release ──────────────────────────────────────────────────────────

build: ## Build package
	$(PYTHON) -m build

publish-test: ## Publish to TestPyPI
	twine upload --repository testpypi dist/*

publish: ## Publish to PyPI
	twine upload dist/*

# ─── Cleanup ──────────────────────────────────────────────────────────

clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .mypy_cache .ruff_cache htmlcov/
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
