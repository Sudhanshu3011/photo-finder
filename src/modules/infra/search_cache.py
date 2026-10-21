"""
src/modules/infra/search_cache.py — Two-Tier Cryptographic Search Caching Engine.

Provides:
- L1 In-Memory Thread-Safe LRU/TTL Cache (< 0.1ms) for instantaneous pagination and gallery browsing.
- L2 Distributed Redis Cache (< 1.5ms) across API pods using deterministic SHA-256 key hashing.
- O(1) Generation-Based Tenant Cache Invalidation (eliminates thread-blocking Redis KEYS/pattern scans).
"""
import collections
import hashlib
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np

from src.core.config import (
    ENABLE_SEARCH_CACHE,
    SEARCH_CACHE_L1_SIZE,
    SEARCH_CACHE_L1_TTL,
    SEARCH_CACHE_L2_TTL,
)
from src.core.tenant_context import get_current_tenant_id
from src.modules.infra.kv_cache import get_kv_cache, KeyValueCache

logger = logging.getLogger("src.modules.infra.search_cache")


class ThreadSafeTTLCache:
    """Thread-safe in-memory LRU cache with per-item TTL expiration."""

    def __init__(self, maxsize: int = 10000, default_ttl: float = 300.0):
        self.maxsize = maxsize
        self.default_ttl = default_ttl
        self._store: collections.OrderedDict[str, Tuple[Any, float]] = collections.OrderedDict()
        self._lock = threading.RLock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key not in self._store:
                self.misses += 1
                return None

            value, expiry = self._store[key]
            if time.time() > expiry:
                del self._store[key]
                self.misses += 1
                return None

            # Move to end (most recently used)
            self._store.move_to_end(key)
            self.hits += 1
            return value

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        expiry = time.time() + (ttl if ttl is not None else self.default_ttl)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (value, expiry)

            # Evict oldest if maxsize exceeded
            while len(self._store) > self.maxsize:
                self._store.popitem(last=False)

    def delete(self, key: str) -> bool:
        with self._lock:
            if key in self._store:
                del self._store[key]
                return True
            return False

    def evict_by_prefix(self, prefix: str) -> int:
        """Evict all keys starting with prefix while keeping unrelated cache entries intact."""
        with self._lock:
            to_delete = [k for k in self._store.keys() if k.startswith(prefix)]
            for k in to_delete:
                del self._store[k]
            return len(to_delete)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0

    def size(self) -> int:
        with self._lock:
            return len(self._store)


class SearchCacheManager:
    """Two-tier search cache orchestrating L1 in-memory and L2 Redis distributed caching."""

    def __init__(
        self,
        l1_size: int = SEARCH_CACHE_L1_SIZE,
        l1_ttl: float = float(SEARCH_CACHE_L1_TTL),
        l2_ttl: int = SEARCH_CACHE_L2_TTL,
        kv_cache: Optional[KeyValueCache] = None,
    ):
        self.l1 = ThreadSafeTTLCache(maxsize=l1_size, default_ttl=l1_ttl)
        self.l2_ttl = l2_ttl
        self.kv = kv_cache or get_kv_cache()
        self._local_generations: Dict[str, int] = {}
        self._gen_lock = threading.RLock()

    def get_tenant_generation(self, tenant_id: str) -> int:
        """Fetch current search cache generation for tenant in O(1)."""
        tid = (tenant_id or "default").strip()
        # Check Redis synchronous client
        sync_redis = self.kv.get_sync_redis()
        if sync_redis:
            try:
                gen_str = sync_redis.get(f"tenant:{tid}:search_gen")
                if gen_str is not None:
                    gen_val = int(gen_str)
                    with self._gen_lock:
                        self._local_generations[tid] = gen_val
                    return gen_val
                else:
                    sync_redis.set(f"tenant:{tid}:search_gen", "1")
                    with self._gen_lock:
                        self._local_generations[tid] = 1
                    return 1
            except Exception as e:
                logger.debug("Failed to read search_gen from Redis (%s); using local counter", e)

        with self._gen_lock:
            return self._local_generations.get(tid, 1)

    def invalidate_tenant(self, tenant_id: str) -> int:
        """
        Atomically increment tenant search generation in O(1).
        Instantly invalidates all cached search queries for this tenant across all API pods
        and purges local in-memory L1 cache entries for this specific tenant.
        """
        tid = (tenant_id or "default").strip()
        new_gen = 2
        sync_redis = self.kv.get_sync_redis()
        if sync_redis:
            try:
                new_gen = sync_redis.incr(f"tenant:{tid}:search_gen")
                logger.info("Incremented search_gen for tenant '%s' to %d in Redis", tid, new_gen)
                sync_redis.publish("tenant:cache_invalidation", tid)
            except Exception as e:
                logger.warning("Redis incr failed on tenant search_gen (%s); incrementing local", e)
                with self._gen_lock:
                    new_gen = self._local_generations.get(tid, 1) + 1
                    self._local_generations[tid] = new_gen
        else:
            with self._gen_lock:
                new_gen = self._local_generations.get(tid, 1) + 1
                self._local_generations[tid] = new_gen

        with self._gen_lock:
            self._local_generations[tid] = new_gen

        # Evict local L1 cache entries strictly for this tenant
        prefix = f"cache:search:{tid}:"
        evicted = self.l1.evict_by_prefix(prefix)
        logger.debug("Evicted %d local L1 entries for tenant '%s'", evicted, tid)

        return new_gen

    def handle_invalidation_broadcast(self, tenant_id: str) -> int:
        """Handler for multi-pod cache invalidation broadcast events."""
        tid = (tenant_id or "default").strip()
        prefix = f"cache:search:{tid}:"
        with self._gen_lock:
            self._local_generations.pop(tid, None)
        return self.l1.evict_by_prefix(prefix)

    def make_cache_key(
        self,
        domain: str,
        query_vector: Union[List[float], np.ndarray],
        top_k: int,
        threshold: float,
        filter_dict: Optional[dict] = None,
        tenant_id: Optional[str] = None,
    ) -> str:
        """
        Generate deterministic cryptographic cache key via SHA-256.
        Prevents Python hash() randomization across different API pods and restarts.
        """
        tid = (tenant_id or get_current_tenant_id()).strip()
        gen_id = self.get_tenant_generation(tid)

        vec_arr = np.ascontiguousarray(query_vector, dtype=np.float32)
        vec_bytes = vec_arr.tobytes()
        vec_sha256 = hashlib.sha256(vec_bytes).hexdigest()[:16]

        filter_hash = "all"
        if filter_dict:
            filter_str = json.dumps(filter_dict, sort_keys=True, default=str)
            filter_hash = hashlib.sha256(filter_str.encode("utf-8")).hexdigest()[:8]

        return f"cache:search:{tid}:g{gen_id}:{domain}:{vec_sha256}:k{top_k}:th{threshold:.2f}:f{filter_hash}"

    def get(self, key: str) -> Optional[List[dict]]:
        """Retrieve from L1 (in-memory) or fallback to L2 (Redis)."""
        if not ENABLE_SEARCH_CACHE:
            return None

        # 1. Check L1 In-Memory LRU Cache (< 0.1ms)
        cached_l1 = self.l1.get(key)
        if cached_l1 is not None:
            return cached_l1

        # 2. Check L2 Distributed Redis Cache (< 1.5ms)
        sync_redis = self.kv.get_sync_redis()
        if sync_redis:
            try:
                raw_l2 = sync_redis.get(key)
                if raw_l2:
                    data = json.loads(raw_l2) if isinstance(raw_l2, str) else raw_l2
                    if isinstance(data, list):
                        # Populate L1 on L2 hit
                        self.l1.set(key, data)
                        return data
            except Exception as e:
                logger.debug("L2 search cache get error (%s)", e)

        return None

    def set(self, key: str, results: List[dict]) -> None:
        """Write results to both L1 (in-memory) and L2 (Redis)."""
        if not ENABLE_SEARCH_CACHE or not results:
            return

        # Write to L1 In-Memory
        self.l1.set(key, results)

        # Write to L2 Redis with TTL
        sync_redis = self.kv.get_sync_redis()
        if sync_redis:
            try:
                serialized = json.dumps(results, default=str)
                sync_redis.set(key, serialized, ex=self.l2_ttl)
            except Exception as e:
                logger.debug("L2 search cache set error (%s)", e)


search_cache_manager = SearchCacheManager()


def get_search_cache() -> SearchCacheManager:
    """Return the global SearchCacheManager singleton."""
    return search_cache_manager
