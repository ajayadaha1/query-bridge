"""Tests for SQLGuard."""

import pytest
from querybridge.safety.guard import SQLGuard


class TestSQLGuard:
    def setup_method(self):
        self.guard = SQLGuard(dialect="postgresql")

    def test_valid_select(self):
        is_safe, reason = self.guard.validate("SELECT * FROM users")
        assert is_safe

    def test_valid_with_cte(self):
        is_safe, reason = self.guard.validate(
            "WITH cte AS (SELECT id FROM users) SELECT * FROM cte"
        )
        assert is_safe

    def test_blocks_drop(self):
        is_safe, reason = self.guard.validate("DROP TABLE users")
        assert not is_safe
        assert "blocked" in reason.lower() or "select" in reason.lower()

    def test_blocks_delete(self):
        is_safe, reason = self.guard.validate("DELETE FROM users WHERE id = 1")
        assert not is_safe

    def test_blocks_insert(self):
        is_safe, reason = self.guard.validate("INSERT INTO users VALUES (1, 'test')")
        assert not is_safe

    def test_blocks_update(self):
        is_safe, reason = self.guard.validate("UPDATE users SET name='x'")
        assert not is_safe

    def test_blocks_truncate(self):
        is_safe, reason = self.guard.validate("TRUNCATE users")
        assert not is_safe

    def test_blocks_semicolon_injection(self):
        is_safe, reason = self.guard.validate("SELECT 1; DROP TABLE users")
        assert not is_safe

    def test_empty_query(self):
        is_safe, reason = self.guard.validate("")
        assert not is_safe

    def test_blocks_alter(self):
        is_safe, reason = self.guard.validate("ALTER TABLE users ADD COLUMN x INT")
        assert not is_safe

    def test_allows_ilike(self):
        is_safe, reason = self.guard.validate(
            "SELECT * FROM users WHERE name ILIKE '%test%'"
        )
        assert is_safe

    def test_max_query_length(self):
        guard = SQLGuard(max_query_length=50)
        is_safe, reason = guard.validate("SELECT " + "x" * 100)
        assert not is_safe
        assert "too long" in reason.lower()


class TestSQLGuardDialects:
    def test_postgresql_blocks_copy(self):
        guard = SQLGuard(dialect="postgresql")
        is_safe, reason = guard.validate("COPY users TO '/tmp/out.csv'")
        assert not is_safe

    def test_sqlite_blocks_attach(self):
        guard = SQLGuard(dialect="sqlite")
        is_safe, reason = guard.validate("ATTACH DATABASE '/etc/passwd' AS pwn")
        assert not is_safe
