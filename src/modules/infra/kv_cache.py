"""
src/modules/infra/kv_cache.py — In-Memory & SQLite hybrid Key-Value Cache.
Provides fast in-process caching with TTL and persistent SQLite fallback.
"""
import json
import time
from typing import Any, List, Optional

from src.modules.infra.sqlite_repository import (
    db_cache_get,
    db_cache_set,
    db_cache_delete,
)


class KeyValueCache:
    """Cache service backed by in-memory dictionary and SQLite."""

    def __init__(self):
        self._mem_store: dict[str, tuple[Any, float]] = {}
        self._lists: dict[str, list] = {}

    def get(self, key: str) -> Optional[Any]:
        """Synchronous/in-memory get."""
        if key in self._mem_store:
            val, exp = self._mem_store[key]
            if exp == 0 or exp > time.time():
                return val
            del self._mem_store[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Synchronous in-memory set."""
        exp = (time.time() + ttl) if ttl else 0
        self._mem_store[key] = (value, exp)

    async def aget(self, key: str) -> Optional[str]:
        # Fast in-memory check
        val = self.get(key)
        if val is not None:
            return str(val)

        # SQLite fallback
        res = await db_cache_get(key)
        if res is not None:
            return str(res)
        return None

    async def aset(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        self.set(key, value, ttl=ttl)
        await db_cache_set(key, str(value), ttl_seconds=ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.aget(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self.aset(key, json.dumps(value), ttl=ttl)

    async def delete(self, key: str) -> None:
        self._mem_store.pop(key, None)
        await db_cache_delete(key)

    async def lpush(self, key: str, value: str) -> None:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)

    async def rpop(self, key: str) -> Optional[str]:
        if key in self._lists and self._lists[key]:
            return self._lists[key].pop()
        return None


cache = KeyValueCache()


def get_kv_cache() -> KeyValueCache:
    return cache

