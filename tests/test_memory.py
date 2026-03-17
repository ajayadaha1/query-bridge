"""Tests for memory and context management."""

from querybridge.agent.context import ContextWindowManager
from querybridge.memory.conversation import ConversationMemory
from querybridge.memory.store import MemoryStore


class TestConversationMemory:
    def test_create_memory(self):
        mem = ConversationMemory("test-session")
        assert mem.chat_id == "test-session"

    def test_add_verified_filter(self):
        mem = ConversationMemory("test")
        mem.add_verified_filter("customer=Acme", 42)
        text = mem.format_for_prompt()
        assert "Acme" in text or "customer" in text

    def test_add_successful_pattern(self):
        mem = ConversationMemory("test")
        mem.add_successful_pattern("count", "Used COUNT(*)")
        # Should not error
        assert True


class TestMemoryStore:
    def test_get_creates_session(self):
        store = MemoryStore()
        mem = store.get("session-1")
        assert mem is not None
        assert mem.chat_id == "session-1"

    def test_same_session_returned(self):
        store = MemoryStore()
        mem1 = store.get("session-1")
        mem2 = store.get("session-1")
        assert mem1 is mem2


class TestContextWindowManager:
    def test_track_message(self):
        ctx = ContextWindowManager()
        ctx.track_message({"role": "user", "content": "Hello"})
        assert ctx.current_estimate > 0

    def test_compress_doesnt_crash_on_small(self):
        ctx = ContextWindowManager()
        messages = [
            {"role": "system", "content": "You are helpful"},
            {"role": "user", "content": "Hi"},
        ]
        result = ctx.compress_history(messages)
        assert len(result) == 2

    def test_truncate_within_budget(self):
        ctx = ContextWindowManager()
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
        ]
        result = ctx.truncate_to_budget(messages)
        assert len(result) == 2

    def test_usage_report(self):
        ctx = ContextWindowManager()
        ctx.track_message({"role": "user", "content": "test"})
        report = ctx.get_usage_report()
        assert "estimated_chars" in report
        assert "usage_pct" in report
