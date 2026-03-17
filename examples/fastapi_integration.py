"""Embed QueryBridge in a FastAPI application."""

from fastapi import FastAPI
from querybridge import QueryBridgeEngine
from querybridge.connectors.postgresql import PostgreSQLConnector
from querybridge.llm.openai_provider import OpenAIProvider
from querybridge.server.api import create_app as create_querybridge_app

# Option 1: Use the built-in QueryBridge API app
app = create_querybridge_app(
    engine=QueryBridgeEngine(
        connector=PostgreSQLConnector("postgresql://user:pass@localhost/mydb"),
        llm=OpenAIProvider(api_key="sk-..."),
    )
)

# Option 2: Mount QueryBridge under your existing app
# your_app = FastAPI()
#
# qb_engine = QueryBridgeEngine(
#     connector=PostgreSQLConnector("postgresql://user:pass@localhost/mydb"),
#     llm=OpenAIProvider(api_key="sk-..."),
# )
#
# @your_app.post("/ask")
# async def ask(question: str):
#     response = await qb_engine.query(question)
#     return {"answer": response.answer, "sql": response.last_sql}
#
# # Run: uvicorn examples.fastapi_integration:your_app
