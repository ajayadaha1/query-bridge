"""Tests for ResultValidator."""

import pytest
from querybridge.safety.validator import ResultValidator


class TestResultValidator:
    def setup_method(self):
        self.validator = ResultValidator()

    def test_zero_rows_flagged(self):
        result = {"row_count": 0, "rows": [], "columns": ["id"]}
        v = self.validator.validate(result, "SELECT * FROM users")
        assert v.has_issues()
        assert any("zero" in n.message.lower() or "0 row" in n.message.lower() for n in v.notes)

    def test_normal_result_no_issues(self):
        result = {
            "row_count": 5,
            "rows": [{"id": i, "name": f"user{i}"} for i in range(5)],
            "columns": ["id", "name"],
        }
        v = self.validator.validate(result, "SELECT * FROM users")
        assert not v.has_issues()

    def test_high_null_rate(self):
        rows = [{"id": i, "name": None} for i in range(10)]
        result = {"row_count": 10, "rows": rows, "columns": ["id", "name"]}
        v = self.validator.validate(result, "SELECT id, name FROM users")
        # Should detect high null rate in 'name' column
        assert v.has_issues()


class TestResultValidatorExpectations:
    def test_suspiciously_few_rows(self):
        validator = ResultValidator()
        validator.set_expectations(expected=1000)
        result = {
            "row_count": 1,
            "rows": [{"id": 1}],
            "columns": ["id"],
        }
        v = validator.validate(result, "SELECT * FROM users")
        assert v.has_issues()
