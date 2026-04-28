"""
src/services/cache.py — Phase 3: Upstash Redis wrapper

Provides a thin async layer over Upstash Redis (REST API, so no socket
connection required — works fine on HF free tier which blocks raw TCP to
external hosts).

Falls back gracefully to a local in-memory dict if UPSTASH_REDIS_URL is not
set, so the rest of the codebase can import and call CacheService without
any conditional guards.

Usage:
    from src.services.cache import cache
    await cache.set("key", "value", ttl=3600)
    val = await cache.get("key")          # returns str | None
    await cache.delete("key")
    await cache.lpush("list_key", "item")
    items = await cache.lrange("list_key", 0, -1)
"""

import json
import os
import time
from typing import Any, Optional

import aiohttp

UPSTASH_REDIS_URL = os.getenv("UPSTASH_REDIS_URL", "")
UPSTASH_REDIS_TOKEN = os.getenv("UPSTASH_REDIS_TOKEN", "")

# Fallback in-memory store used when Upstash is not configured.
_mem_store: dict[str, tuple[Any, float]] = {}  # key → (value, expires_at or 0)


class CacheService:
    """
    Async Redis cache backed by Upstash REST API.
    Falls back to an in-memory dict when Upstash is not configured.
    """

    def __init__(self):
        self._enabled = bool(UPSTASH_REDIS_URL and UPSTASH_REDIS_TOKEN)
        self._base_url = UPSTASH_REDIS_URL.rstrip("/") if self._enabled else ""
        self._headers = (
            {"Authorization": f"Bearer {UPSTASH_REDIS_TOKEN}"}
            if self._enabled
            else {}
        )
        if not self._enabled:
            print("[Cache] Upstash not configured — using in-memory fallback")

    # ── Internal REST call ────────────────────────────────────────────
    async def _cmd(self, *args) -> Any:
        """Execute a Redis command via the Upstash REST API."""
        url = f"{self._base_url}/{'/'.join(str(a) for a in args)}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=self._headers) as resp:
                data = await resp.json()
                if "error" in data:
                    raise RuntimeError(f"Upstash error: {data['error']}")
                return data.get("result")

    # ── Public API ────────────────────────────────────────────────────
    async def get(self, key: str) -> Optional[str]:
        if not self._enabled:
            entry = _mem_store.get(key)
            if entry is None:
                return None
            val, exp = entry
            if exp and time.time() > exp:
                _mem_store.pop(key, None)
                return None
            return val

        result = await self._cmd("GET", key)
        return result  # str or None

    async def set(self, key: str, value: Any, ttl: int = 0) -> bool:
        """
        Store value under key. If ttl > 0, key expires after that many seconds.
        Value is JSON-serialised if not already a str.
        """
        if not isinstance(value, str):
            value = json.dumps(value)

        if not self._enabled:
            exp = time.time() + ttl if ttl else 0
            _mem_store[key] = (value, exp)
            return True

        if ttl:
            await self._cmd("SET", key, value, "EX", ttl)
        else:
            await self._cmd("SET", key, value)
        return True

    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def set_json(self, key: str, value: Any, ttl: int = 0) -> bool:
        return await self.set(key, json.dumps(value), ttl=ttl)

    async def delete(self, key: str) -> bool:
        if not self._enabled:
            _mem_store.pop(key, None)
            return True
        await self._cmd("DEL", key)
        return True

    async def exists(self, key: str) -> bool:
        if not self._enabled:
            return await self.get(key) is not None
        result = await self._cmd("EXISTS", key)
        return bool(result)

    async def incr(self, key: str) -> int:
        if not self._enabled:
            entry = _mem_store.get(key, ("0", 0))
            new_val = int(entry[0]) + 1
            _mem_store[key] = (str(new_val), entry[1])
            return new_val
        result = await self._cmd("INCR", key)
        return int(result)

    async def expire(self, key: str, ttl: int) -> bool:
        if not self._enabled:
            if key in _mem_store:
                val, _ = _mem_store[key]
                _mem_store[key] = (val, time.time() + ttl)
            return True
        await self._cmd("EXPIRE", key, ttl)
        return True

    # ── List ops (used for job queue) ─────────────────────────────────
    async def lpush(self, key: str, *values: str) -> int:
        """Push values to the LEFT of a list (queue head)."""
        if not self._enabled:
            lst = json.loads(_mem_store.get(key, ("[]", 0))[0])
            for v in values:
                lst.insert(0, v)
            _mem_store[key] = (json.dumps(lst), 0)
            return len(lst)
        for v in values:
            await self._cmd("LPUSH", key, v)
        return 0  # Upstash REST returns the new length; we don't need it here

    async def rpop(self, key: str) -> Optional[str]:
        """Pop one value from the RIGHT of a list (queue tail = oldest item)."""
        if not self._enabled:
            lst = json.loads(_mem_store.get(key, ("[]", 0))[0])
            if not lst:
                return None
            val = lst.pop()
            _mem_store[key] = (json.dumps(lst), 0)
            return val
        return await self._cmd("RPOP", key)

    async def llen(self, key: str) -> int:
        if not self._enabled:
            lst = json.loads(_mem_store.get(key, ("[]", 0))[0])
            return len(lst)
        result = await self._cmd("LLEN", key)
        return int(result or 0)

    async def lrange(self, key: str, start: int, stop: int) -> list[str]:
        if not self._enabled:
            lst = json.loads(_mem_store.get(key, ("[]", 0))[0])
            end = None if stop == -1 else stop + 1
            return lst[start:end]
        result = await self._cmd("LRANGE", key, start, stop)
        return result or []

    # ── Rate limiting helper ──────────────────────────────────────────
    async def rate_limit_check(self, key: str, max_calls: int, window_secs: int) -> bool:
        """
        Returns True if the caller is within the rate limit, False if exceeded.
        Uses a simple counter with TTL.
        """
        count = await self.incr(key)
        if count == 1:
            await self.expire(key, window_secs)
        return count <= max_calls


# Module-level singleton — import this everywhere
cache = CacheService()