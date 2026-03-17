# Docker Demo

Try QueryBridge with zero setup using Docker.

## Launch

```bash
git clone https://github.com/querybridge/querybridge
cd querybridge
export OPENAI_API_KEY="sk-..."   # or your preferred LLM key
docker compose up
```

## What's Running

| Service | URL | Description |
|---------|-----|-------------|
| **Playground** | [localhost:3000](http://localhost:3000) | Interactive chat UI |
| **API** | [localhost:8000/docs](http://localhost:8000/docs) | FastAPI Swagger docs |
| **PostgreSQL** | `localhost:5432` | Chinook sample database |

## Sample Questions

Try these in the playground:

- "What are the top 10 best-selling artists?"
- "Which country generates the most revenue?"
- "Show me the monthly sales trend"
- "How many tracks does each genre have?"
- "Compare rock vs jazz track counts"

## Configuration

Override via environment variables:

```bash
# Use a different model
QUERYBRIDGE_MODEL=gpt-4o-mini docker compose up

# Use Anthropic
QUERYBRIDGE_PROVIDER=anthropic QUERYBRIDGE_API_KEY=sk-ant-... docker compose up
```

## Teardown

```bash
docker compose down -v
```
