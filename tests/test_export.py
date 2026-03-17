"""Tests for export module."""

import pytest
from querybridge.export.csv_export import to_csv, to_csv_bytes
from querybridge.export.json_export import to_json


class TestCSVExport:
    def test_basic_csv(self):
        columns = ["id", "name"]
        rows = [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        result = to_csv(columns, rows)
        assert "id,name" in result
        assert "Alice" in result
        assert "Bob" in result

    def test_csv_bytes(self):
        columns = ["id"]
        rows = [{"id": 1}]
        result = to_csv_bytes(columns, rows)
        assert isinstance(result, bytes)

    def test_empty_rows(self):
        result = to_csv(["id"], [])
        assert "id" in result


class TestJSONExport:
    def test_basic_json(self):
        columns = ["id", "name"]
        rows = [{"id": 1, "name": "Alice"}]
        result = to_json(columns, rows)
        assert '"columns"' in result
        assert '"rows"' in result
        assert '"row_count": 1' in result

    def test_with_metadata(self):
        result = to_json(["id"], [{"id": 1}], metadata={"query": "SELECT 1"})
        assert '"metadata"' in result
