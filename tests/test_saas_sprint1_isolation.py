"""
tests/test_saas_sprint1_isolation.py — Automated Verification Suite for SaaS Sprint 1.

Validates:
1. Pillar 1: PostgreSQL Row-Level Security (RLS) schema compliance and cross-tenant leakage prevention.
2. Pillar 3: Contextvars tenant context propagation across ThreadPoolExecutor workers.
3. Pillar 5: FAISS LRU in-memory index eviction policy preventing RAM exhaustion under multi-tenant scale.
4. Pillar 7: Selective L1 tenant cache prefix eviction and multi-pod invalidation handling.
"""
import asyncio
import os
import tempfile
import numpy as np
import pytest

from src.core.tenant_context import (
    get_current_tenant_id,
    set_current_tenant_id,
    tenant_context,
    run_in_tenant_thread,
    TenantPreservingThreadPoolExecutor,
    run_async_in_tenant_thread,
)
from src.modules.infra.postgres_repository import (
    get_repository,
    verify_tenant_isolation_compliance,
    sync_verify_tenant_isolation_compliance,
    get_postgres_pool,
    get_tenant_connection,
)
from src.modules.infra.faiss_engine import FAISSEngine, IDX_FACES, FACE_DIM
from src.modules.infra.search_cache import SearchCacheManager, ThreadSafeTTLCache


# -----------------------------------------------------------------------------
# Pillar 1: Tenant Data Isolation & RLS Compliance
# -----------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_database_rls_compliance_audit():
    """Verify that all tenant-scoped PostgreSQL tables have RLS enabled and forced."""
    audit = await verify_tenant_isolation_compliance()
    assert audit["compliant"] is True
    assert audit["status"] in ("verified", "in_memory_fallback")

    if audit["status"] == "verified":
        tables = audit["tables"]
        for tbl in ["photos", "upload_jobs", "face_clusters", "vector_metadata", "folders"]:
            assert tbl in tables
            assert tables[tbl]["has_tenant_id_column"] is True
            assert tables[tbl]["row_security_enabled"] is True
            assert tables[tbl]["row_security_forced"] is True


@pytest.mark.asyncio
async def test_database_rls_cross_tenant_isolation():
    """Verify dual concurrent database sessions cannot read across tenant boundaries."""
    pool = await get_postgres_pool()
    if not pool:
        pytest.skip("PostgreSQL pool not configured; running in mock fallback mode")

    tenant_a = f"t_alpha_{os.urandom(4).hex()}"
    tenant_b = f"t_beta_{os.urandom(4).hex()}"

    # Insert under Tenant A
    async with get_tenant_connection(tenant_a) as conn_a:
        await conn_a.execute(
            """
            INSERT INTO upload_jobs (job_id, tenant_id, user_id, folder, status)
            VALUES ($1, $2, $3, $4, $5)
            """,
            f"job_{tenant_a}_1", tenant_a, "user_a", "vacation", "completed"
        )

    # Insert under Tenant B
    async with get_tenant_connection(tenant_b) as conn_b:
        await conn_b.execute(
            """
            INSERT INTO upload_jobs (job_id, tenant_id, user_id, folder, status)
            VALUES ($1, $2, $3, $4, $5)
            """,
            f"job_{tenant_b}_1", tenant_b, "user_b", "vacation", "completed"
        )

    # Query from Tenant A connection: MUST NOT see Tenant B
    async with get_tenant_connection(tenant_a) as conn_a:
        rows_a = await conn_a.fetch("SELECT job_id, tenant_id FROM upload_jobs")
        t_ids = {r["tenant_id"] for r in rows_a}
        assert tenant_b not in t_ids
        assert all(r["tenant_id"] == tenant_a for r in rows_a)

    # Query from Tenant B connection: MUST NOT see Tenant A
    async with get_tenant_connection(tenant_b) as conn_b:
        rows_b = await conn_b.fetch("SELECT job_id, tenant_id FROM upload_jobs")
        t_ids = {r["tenant_id"] for r in rows_b}
        assert tenant_a not in t_ids
        assert all(r["tenant_id"] == tenant_b for r in rows_b)


# -----------------------------------------------------------------------------
# Pillar 3: Tenant Identification & Thread Boundary Context Propagation
# -----------------------------------------------------------------------------

def test_tenant_contextvars_threading_fidelity():
    """Verify run_in_tenant_thread and TenantPreservingThreadPoolExecutor carry contextvars."""
    with tenant_context("tenant_thread_test_1"):
        assert get_current_tenant_id() == "tenant_thread_test_1"

        def get_worker_tid():
            return get_current_tenant_id()

        # 1. run_in_tenant_thread helper
        result_tid = run_in_tenant_thread(get_worker_tid)
        assert result_tid == "tenant_thread_test_1"

        # 2. Custom TenantPreservingThreadPoolExecutor
        with TenantPreservingThreadPoolExecutor(max_workers=2) as executor:
            future = executor.submit(get_worker_tid)
            assert future.result() == "tenant_thread_test_1"


@pytest.mark.asyncio
async def test_async_thread_tenant_context_preservation():
    """Verify run_async_in_tenant_thread preserves tenant across async thread execution."""
    async def task(tid: str):
        with tenant_context(tid):
            await asyncio.sleep(0.01)
            # Run blocking task in executor
            worker_tid = await run_async_in_tenant_thread(get_current_tenant_id)
            return worker_tid

    results = await asyncio.gather(
        task("tenant_async_x"),
        task("tenant_async_y"),
        task("tenant_async_z"),
    )
    assert results == ["tenant_async_x", "tenant_async_y", "tenant_async_z"]


# -----------------------------------------------------------------------------
# Pillar 5: AI / FAISS Memory Management & LRU Eviction
# -----------------------------------------------------------------------------

def test_faiss_lru_memory_eviction(tmp_path):
    """Verify FAISSEngine evicts least-recently-used tenant indices when capacity is reached."""
    engine = FAISSEngine(data_dir=str(tmp_path / "faiss_lru"))
    # Restrict memory capacity to 3 active tenant indices
    engine.max_loaded_indices = 3

    tenants = [f"tenant_lru_{i}" for i in range(5)]
    dim = FACE_DIM

    # Ingest 1 vector for each of the 5 tenants
    for idx, tid in enumerate(tenants):
        vec = np.ones(dim, dtype=np.float32) * (idx + 1)
        vec = (vec / np.linalg.norm(vec)).tolist()
        engine.upsert(
            IDX_FACES,
            records=[{"id": f"img_{tid}", "vector": vec, "url": f"https://s3/{tid}.jpg"}],
            tenant_id=tid,
        )

    # In-memory index dictionary must not exceed max_loaded_indices
    with engine.lock:
        assert len(engine.indices) <= 3, f"Expected <= 3 loaded indices in RAM, found {len(engine.indices)}"

    # Query the first tenant (which was evicted from memory to disk)
    vec_0 = np.ones(dim, dtype=np.float32)
    vec_0 = (vec_0 / np.linalg.norm(vec_0)).tolist()

    res_0 = engine.search(IDX_FACES, query_vector=vec_0, top_k=5, tenant_id=tenants[0])
    assert len(res_0) == 1
    assert res_0[0]["id"] == f"img_{tenants[0]}"
    assert res_0[0]["score"] >= 0.99

    # Verifies index was transparently reloaded into RAM
    with engine.lock:
        assert (tenants[0], IDX_FACES) in engine.indices
        assert len(engine.indices) <= 3


# -----------------------------------------------------------------------------
# Pillar 7: Cache Leakage Prevention & Selective Tenant L1 Eviction
# -----------------------------------------------------------------------------

def test_cache_selective_tenant_l1_eviction():
    """Verify invalidating Tenant Alpha purges Alpha's L1 cache while leaving Tenant Beta intact."""
    cache = SearchCacheManager(l1_size=50, l1_ttl=60.0)
    tenant_alpha = f"t_alpha_{os.urandom(4).hex()}"
    tenant_beta = f"t_beta_{os.urandom(4).hex()}"

    q_vec = np.random.randn(512).astype(np.float32)
    q_vec = q_vec / np.linalg.norm(q_vec)

    key_alpha = cache.make_cache_key("faces", q_vec, 10, 0.25, tenant_id=tenant_alpha)
    key_beta = cache.make_cache_key("faces", q_vec, 10, 0.25, tenant_id=tenant_beta)

    # Populate L1 for both tenants
    cache.set(key_alpha, [{"id": "alpha_1"}])
    cache.set(key_beta, [{"id": "beta_1"}])

    assert cache.get(key_alpha) is not None
    assert cache.get(key_beta) is not None

    # Invalidate Tenant Alpha
    cache.invalidate_tenant(tenant_alpha)

    # Tenant Alpha's old key must be purged from local L1
    assert cache.l1.get(key_alpha) is None

    # Tenant Beta's L1 entry MUST still be warm and intact
    assert cache.l1.get(key_beta) is not None
    assert cache.l1.get(key_beta)[0]["id"] == "beta_1"


def test_cache_handle_invalidation_broadcast():
    """Verify multi-pod invalidation handler selectively evicts local L1 entries."""
    cache = SearchCacheManager(l1_size=50, l1_ttl=60.0)
    tid = f"tenant_broadcast_{os.urandom(4).hex()}"

    q_vec = np.random.randn(512).astype(np.float32)
    key = cache.make_cache_key("faces", q_vec, 10, 0.25, tenant_id=tid)
    cache.set(key, [{"id": "cached_item"}])

    assert cache.get(key) is not None

    # Simulate receiving invalidation broadcast from another API pod
    evicted = cache.handle_invalidation_broadcast(tid)
    assert evicted >= 1
    assert cache.l1.get(key) is None

