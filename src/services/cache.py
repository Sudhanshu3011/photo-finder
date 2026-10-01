"""
src/services/cache.py — Local In-Memory & SQLite Cache Service.
Zero external Redis dependencies: provides fast async caching, TTL expiration, and atomic counters.
"""
import json
import time
from typing import Any, List, Optional

from src.services.local_db import (
    local_cache_get,
    local_cache_set,
    local_cache_incr,
    local_cache_delete,
)


class CacheService:
    """Async Cache service backed by local SQLite and in-memory cache."""

    def __init__(self):
        self._mem_store: dict[str, tuple[Any, float]] = {}
        self._lists: dict[str, list] = {}

    async def get(self, key: str) -> Optional[str]:
        # Fast in-memory check
        if key in self._mem_store:
            val, exp = self._mem_store[key]
            if exp == 0 or exp > time.time():
                return str(val) if val is not None else None
            del self._mem_store[key]

        # SQLite persistent fallback
        res = await local_cache_get(key)
        if res is not None:
            return str(res)
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        exp = (time.time() + ttl) if ttl else 0
        self._mem_store[key] = (value, exp)
        await local_cache_set(key, value, ttl=ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return raw

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        await self.set(key, json.dumps(value), ttl=ttl)

    async def delete(self, key: str) -> None:
        self._mem_store.pop(key, None)
        await local_cache_delete(key)

    async def incr(self, key: str) -> int:
        return await local_cache_incr(key)

    async def lpush(self, key: str, item: Any) -> int:
        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, item)
        return len(self._lists[key])

    async def rpop(self, key: str) -> Optional[Any]:
        if key in self._lists and self._lists[key]:
            return self._lists[key].pop()
        return None

    async def lrange(self, key: str, start: int, stop: int) -> List[Any]:
        lst = self._lists.get(key, [])
        if stop == -1:
            return lst[start:]
        return lst[start:stop + 1]


# Global cache singleton
cache = CacheService()