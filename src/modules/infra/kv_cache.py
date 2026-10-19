"""
src/modules/infra/kv_cache.py — Distributed Redis & In-Memory Cache.
Provides sub-millisecond ephemeral state for jobs, rate limiting, and temporary tokens.
Supports standard Redis and AWS ElastiCache via REDIS_URL.
"""
import ast
import json
import logging
import os
import time
from typing import Any, List, Optional

logger = logging.getLogger("src.modules.infra.kv_cache")

try:
    import redis.asyncio as aioredis
    import redis as sync_redis_lib
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    aioredis = None
    sync_redis_lib = None


class KeyValueCache:
    """Distributed cache with Redis backend and in-memory fallback."""

    def __init__(self):
        self._mem_store: dict[str, tuple[Any, float]] = {}
        self._lists: dict[str, list] = {}
        self._redis_client: Optional[Any] = None
        self._sync_redis_client: Optional[Any] = None
        self._redis_checked: bool = False
        self._sync_redis_checked: bool = False
        self._redis_url: str = os.getenv("REDIS_URL", "").strip()

    def get_sync_redis(self) -> Optional[Any]:
        """Lazy initialization of synchronous Redis client for Celery workers."""
        if not HAS_REDIS or not self._redis_url:
            return None
        if self._sync_redis_client is None and not self._sync_redis_checked:
            self._sync_redis_checked = True
            try:
                client = sync_redis_lib.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=3.0,
                )
                client.ping()
                self._sync_redis_client = client
                logger.info("Connected to synchronous Redis cache at %s", self._redis_url)
            except Exception as e:
                logger.warning("Sync Redis connection failed (%s); using in-memory cache.", e)
                self._sync_redis_client = None
        return self._sync_redis_client

    async def _get_redis(self) -> Optional[Any]:
        """Lazy initialization of async Redis client connection pool."""
        if not HAS_REDIS or not self._redis_url:
            return None

        if self._redis_client is None and not self._redis_checked:
            self._redis_checked = True
            try:
                client = aioredis.from_url(
                    self._redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=2.0,
                    socket_timeout=3.0,
                )
                await client.ping()
                self._redis_client = client
                logger.info("Connected to distributed Redis cache at %s", self._redis_url)
            except Exception as e:
                logger.warning("Redis connection failed (%s); using in-memory cache.", e)
                self._redis_client = None

        return self._redis_client

    def get(self, key: str) -> Optional[Any]:
        """Synchronous lookup: checks synchronous Redis first, then in-memory cache."""
        sync_r = self.get_sync_redis()
        if sync_r:
            try:
                val = sync_r.get(key)
                if val is not None:
                    if isinstance(val, str):
                        try:
                            return json.loads(val)
                        except Exception:
                            try:
                                return ast.literal_eval(val)
                            except Exception:
                                return val
                    return val
            except Exception as e:
                logger.debug("Sync Redis get error on key %s: %s", key, e)

        if key in self._mem_store:
            val, exp = self._mem_store[key]
            if exp == 0 or exp > time.time():
                return val
            del self._mem_store[key]
        return None

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Synchronous storage: writes to synchronous Redis and local in-memory store."""
        str_val = json.dumps(value) if isinstance(value, (dict, list)) else (str(value) if not isinstance(value, str) else value)
        sync_r = self.get_sync_redis()
        if sync_r:
            try:
                if ttl:
                    sync_r.set(key, str_val, ex=int(ttl))
                else:
                    sync_r.set(key, str_val)
            except Exception as e:
                logger.debug("Sync Redis set error on key %s: %s", key, e)

        exp = (time.time() + ttl) if ttl else 0
        self._mem_store[key] = (value, exp)

    async def aget(self, key: str) -> Optional[str]:
        """Asynchronous get: checks Redis first, then in-memory cache."""
        redis = await self._get_redis()
        if redis:
            try:
                val = await redis.get(key)
                if val is not None:
                    return str(val)
            except Exception as e:
                logger.debug("Redis aget error on key %s: %s", key, e)

        # In-memory lookup
        val = self.get(key)
        if val is not None:
            return json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        return None

    async def aset(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Asynchronous set: writes to Redis and memory store."""
        str_val = json.dumps(value) if isinstance(value, (dict, list)) else (str(value) if not isinstance(value, str) else value)
        redis = await self._get_redis()
        if redis:
            try:
                if ttl:
                    await redis.set(key, str_val, ex=int(ttl))
                else:
                    await redis.set(key, str_val)
            except Exception as e:
                logger.debug("Redis aset error on key %s: %s", key, e)

        self.set(key, value, ttl=ttl)

    async def get_json(self, key: str) -> Optional[Any]:
        """Retrieve and JSON-deserialize a stored object."""
        raw = await self.aget(key)
        if raw is None:
            return None
        if isinstance(raw, (dict, list)):
            return raw
        try:
            return json.loads(raw)
        except Exception:
            try:
                return ast.literal_eval(raw)
            except Exception:
                return raw

    async def set_json(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """JSON-serialize and store an object."""
        await self.aset(key, json.dumps(value), ttl=ttl)

    async def delete(self, key: str) -> None:
        """Remove a key across Redis and local memory store."""
        redis = await self._get_redis()
        if redis:
            try:
                await redis.delete(key)
            except Exception as e:
                logger.debug("Redis delete error on key %s: %s", key, e)

        sync_r = self.get_sync_redis()
        if sync_r:
            try:
                sync_r.delete(key)
            except Exception:
                pass

        self._mem_store.pop(key, None)

    async def lpush(self, key: str, value: str) -> None:
        """Push an item onto a FIFO/LIFO list."""
        redis = await self._get_redis()
        if redis:
            try:
                await redis.lpush(key, value)
                return
            except Exception as e:
                logger.debug("Redis lpush error on key %s: %s", key, e)

        if key not in self._lists:
            self._lists[key] = []
        self._lists[key].insert(0, value)

    async def rpop(self, key: str) -> Optional[str]:
        """Pop an item from the right side of a list."""
        redis = await self._get_redis()
        if redis:
            try:
                val = await redis.rpop(key)
                return val
            except Exception as e:
                logger.debug("Redis rpop error on key %s: %s", key, e)

        if key in self._lists and self._lists[key]:
            return self._lists[key].pop()
        return None


cache = KeyValueCache()


def get_kv_cache() -> KeyValueCache:
    return cache
