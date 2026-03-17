# Installation

## PyPI (recommended)

```bash
pip install querybridge
```

### With database drivers

=== "PostgreSQL"
    ```bash
    pip install querybridge[postgresql]
    ```

=== "SQLite"
    ```bash
    pip install querybridge[sqlite]
    ```

=== "MySQL"
    ```bash
    pip install querybridge[mysql]
    ```

=== "Everything"
    ```bash
    pip install querybridge[all]
    ```

## From Source

```bash
git clone https://github.com/querybridge/querybridge
cd querybridge
pip install -e ".[dev]"
```

## Docker

```bash
git clone https://github.com/querybridge/querybridge
cd querybridge
docker compose up
```

This starts:

- **PostgreSQL** with sample Chinook music database
- **QueryBridge API** at `http://localhost:8000`
- **Playground UI** at `http://localhost:3000`

## Requirements

- Python 3.10+
- An LLM API key (OpenAI, Anthropic, or any LiteLLM-supported provider)
- A database to query
