# Examples

Runnable scripts showing common QueryBridge patterns.

| File | Description |
|---|---|
| [`quickstart.py`](quickstart.py) | Ask a SQLite database questions in ~10 lines |
| [`multi_llm.py`](multi_llm.py) | Swap between OpenAI, Anthropic, and LiteLLM providers |
| [`fastapi_integration.py`](fastapi_integration.py) | Embed QueryBridge inside a FastAPI app |
| [`custom_plugin.py`](custom_plugin.py) | Create a domain plugin to boost accuracy |

## Prerequisites

```bash
pip install querybridge
# or with extras:
pip install "querybridge[anthropic,postgresql]"
```

## Running

```bash
# Uses the bundled Chinook demo database — no DB setup needed
python examples/quickstart.py
```
