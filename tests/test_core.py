"""Tests for core models and config."""

import pytest
from querybridge.core.config import EngineConfig
from querybridge.core.models import QueryRequest, QueryResponse, QueryLogEntry, TableInfo, ColumnInfo


class TestEngineConfig:
    def test_defaults(self):
        config = EngineConfig()
        assert config.max_iterations == 15
        assert config.max_rows == 500
        assert config.statement_timeout_ms == 10_000
        assert config.model == "gpt-4o"

    def test_custom_values(self):
        config = EngineConfig(max_iterations=5, model="gpt-3.5-turbo")
        assert config.max_iterations == 5
        assert config.model == "gpt-3.5-turbo"


class TestModels:
    def test_query_request(self):
        req = QueryRequest(question="How many users?")
        assert req.question == "How many users?"
        assert req.chat_id is not None  # auto-generated UUID
        assert req.history is None

    def test_query_response(self):
        resp = QueryResponse(
            answer="There are 42 users.",
            chat_id="test-123",
            query_log=[],
            total_time_ms=100,
        )
        assert resp.answer == "There are 42 users."
        assert resp.confidence == 0.0

    def test_table_info(self):
        info = TableInfo(name="users", row_count_estimate=100)
        assert info.name == "users"
        assert info.row_count_estimate == 100

    def test_column_info(self):
        info = ColumnInfo(name="id", data_type="integer", nullable=False)
        assert info.name == "id"
        assert not info.nullable
