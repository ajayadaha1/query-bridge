"""MemoryStore — In-memory session store with TTL eviction."""

from __future__ import annotations

from querybridge.memory.conversation import DEFAULT_TTL_SECONDS, ConversationMemory


class MemoryStore:
    """In-memory store for conversation memories, keyed by chat_id."""

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS, max_sessions: int = 100):
        self._store: dict[str, ConversationMemory] = {}
        self.ttl_seconds = ttl_seconds
        self.max_sessions = max_sessions

    def get(self, chat_id: str) -> ConversationMemory:
        self._evict_expired()
        if chat_id in self._store:
            mem = self._store[chat_id]
            if not mem.is_expired():
                mem.touch()
                return mem
            del self._store[chat_id]

        mem = ConversationMemory(chat_id=chat_id, ttl_seconds=self.ttl_seconds)
        self._store[chat_id] = mem
        return mem

    def has(self, chat_id: str) -> bool:
        if chat_id in self._store:
            if not self._store[chat_id].is_expired():
                return True
            del self._store[chat_id]
        return False

    def clear(self, chat_id: str):
        self._store.pop(chat_id, None)

    def clear_all(self):
        self._store.clear()

    def _evict_expired(self):
        expired = [cid for cid, mem in self._store.items() if mem.is_expired()]
        for cid in expired:
            del self._store[cid]
        if len(self._store) > self.max_sessions:
            sorted_sessions = sorted(self._store.items(), key=lambda x: x[1].last_accessed)
            for cid, _ in sorted_sessions[: len(self._store) - self.max_sessions]:
                del self._store[cid]

    @property
    def active_sessions(self) -> int:
        self._evict_expired()
        return len(self._store)
