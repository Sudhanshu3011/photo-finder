"""
tests/test_phase1_multitenancy.py — Automated verification of Phase 1 Multi-Tenant Isolation.
Tests:
1. Async tenant context propagation via contextvars.
2. JWT token claims containing tenant_id.
3. Tenant-partitioned vector indexing (FAISS / fallback):
   - Tenant A's vectors are invisible to Tenant B.
   - Deletion in Tenant A leaves Tenant B completely unaffected.
4. Distributed Job tracking isolation (IDOR protection):
   - Tenant B cannot read or tamper with Tenant A's background jobs.
5. SQLite Repository multi-tenant scoping for jobs and clusters.
"""
try:
    import pytest
except ImportError:
    class _MockPytestMark:
        @staticmethod
        def asyncio(f):
            return f
    class _MockPytest:
        mark = _MockPytestMark()
    pytest = _MockPytest()

import numpy as np
import asyncio

from src.core.tenant_context import (
    get_current_tenant_id,
    set_current_tenant_id,
    reset_tenant_context,
    tenant_context,
)
from src.modules.auth.jwt_manager import create_access_token, decode_access_token
from src.modules.infra.faiss_engine import FAISSEngine
from src.services.jobs import create_job, update_job_progress, get_job_status
from src.modules.infra.postgres_repository import get_repository


def test_tenant_context_propagation():
    """Verify contextvars-based tenant context default, override, and reset."""
    reset_tenant_context()
    assert get_current_tenant_id() == "default"

    set_current_tenant_id("tenant_enterprise_1")
    assert get_current_tenant_id() == "tenant_enterprise_1"

    reset_tenant_context()
    assert get_current_tenant_id() == "default"

    # Test context manager
    with tenant_context("tenant_org_2"):
        assert get_current_tenant_id() == "tenant_org_2"

    assert get_current_tenant_id() == "default"


@pytest.mark.asyncio
async def test_async_task_context_isolation():
    """Verify that concurrent async tasks maintain distinct tenant contexts."""
    results = {}

    async def worker(tenant_name: str, delay: float):
        with tenant_context(tenant_name):
            await asyncio.sleep(delay)
            results[tenant_name] = get_current_tenant_id()

    await asyncio.gather(
        worker("tenant_alpha", 0.02),
        worker("tenant_beta", 0.01),
        worker("tenant_gamma", 0.03),
    )

    assert results["tenant_alpha"] == "tenant_alpha"
    assert results["tenant_beta"] == "tenant_beta"
    assert results["tenant_gamma"] == "tenant_gamma"


def test_jwt_tenant_claims():
    """Verify that JWT embeds and extracts tenant_id."""
    token = create_access_token(
        data={"sub": "user_123", "role": "admin"},
        tenant_id="tenant_acme",
    )
    payload = decode_access_token(token)
    assert payload is not None
    assert payload["sub"] == "user_123"
    assert payload["tenant_id"] == "tenant_acme"
    assert payload["role"] == "admin"


def test_faiss_tenant_partitioning(tmp_path):
    """Verify complete isolation between Tenant A and Tenant B vectors in FAISSEngine."""
    engine = FAISSEngine(data_dir=str(tmp_path / "faiss"))

    # Vector dimensions (e.g. 512 for ArcFace)
    dim = 512
    vec_a = np.ones(dim, dtype=np.float32).tolist()
    vec_b = (-np.ones(dim, dtype=np.float32)).tolist()

    # Ingest for Tenant A
    engine.upsert(
        index_name="faces",
        records=[{
            "id": "face_tenant_a_1",
            "vector": vec_a,
            "url": "https://cdn.example.com/a1.jpg",
            "folder": "org_a",
            "metadata": {"name": "Alice"},
        }],
        tenant_id="tenant_a",
    )

    # Ingest for Tenant B
    engine.upsert(
        index_name="faces",
        records=[{
            "id": "face_tenant_b_1",
            "vector": vec_b,
            "url": "https://cdn.example.com/b1.jpg",
            "folder": "org_b",
            "metadata": {"name": "Bob"},
        }],
        tenant_id="tenant_b",
    )

    # 1. Search with Tenant A context: must only find Alice
    results_a = engine.search("faces", query_vector=vec_a, top_k=10, tenant_id="tenant_a")
    assert len(results_a) == 1
    assert results_a[0]["id"] == "face_tenant_a_1"
    assert results_a[0]["metadata"]["name"] == "Alice"

    # 2. Search with Tenant B context: must only find Bob
    results_b = engine.search("faces", query_vector=vec_b, top_k=10, tenant_id="tenant_b")
    assert len(results_b) == 1
    assert results_b[0]["id"] == "face_tenant_b_1"
    assert results_b[0]["metadata"]["name"] == "Bob"

    # 3. Cross-tenant leakage check: Tenant B searching for Alice's vector should NOT find Alice
    cross_search = engine.search("faces", query_vector=vec_a, top_k=10, tenant_id="tenant_b")
    # Should only return Tenant B's vectors (or none if score too low), but NEVER Alice
    found_ids = [r["id"] for r in cross_search]
    assert "face_tenant_a_1" not in found_ids

    # 4. Deletion isolation: delete Alice from Tenant A
    engine.delete_by_ids("faces", ["face_tenant_a_1"], tenant_id="tenant_a")
    assert len(engine.search("faces", query_vector=vec_a, top_k=10, tenant_id="tenant_a")) == 0

    # Bob in Tenant B must remain intact
    results_b_post_del = engine.search("faces", query_vector=vec_b, top_k=10, tenant_id="tenant_b")
    assert len(results_b_post_del) == 1
    assert results_b_post_del[0]["id"] == "face_tenant_b_1"


@pytest.mark.asyncio
async def test_job_queue_tenant_idor_protection():
    """Verify that jobs are isolated per tenant and cannot be probed across tenant boundaries."""
    job_id = await create_job(
        user_id="user_alpha",
        folder="vacation",
        total_files=5,
        tenant_id="tenant_alpha",
    )

    await update_job_progress(
        job_id=job_id,
        processed=2,
        total=5,
        stage="processing",
        log_msg="Extracted 2 photos",
        tenant_id="tenant_alpha",
    )

    # Tenant Alpha queries its own job -> Success
    job_alpha = await get_job_status(job_id, tenant_id="tenant_alpha")
    assert job_alpha is not None
    assert job_alpha["job_id"] == job_id
    assert job_alpha["processed_files"] == 2
    assert job_alpha["total_files"] == 5

    # Tenant Beta attempts IDOR probe on Tenant Alpha's job_id -> Blocked (None)
    job_beta = await get_job_status(job_id, tenant_id="tenant_beta")
    assert job_beta is None


def test_repository_face_clusters_isolation():
    """Verify face cluster repository isolates identity groups per tenant."""
    repo = get_repository()

    # Save cluster for Tenant X
    repo.save_face_cluster(
        cluster_id="cluster_x_1",
        person_name="Executive X",
        face_count=12,
        sample_crop_urls=["https://cdn.example.com/crop_x.jpg"],
        user_id="user_x",
        folder="annual_gala",
        tenant_id="tenant_x",
    )

    # Save cluster for Tenant Y
    repo.save_face_cluster(
        cluster_id="cluster_y_1",
        person_name="Engineer Y",
        face_count=8,
        sample_crop_urls=["https://cdn.example.com/crop_y.jpg"],
        user_id="user_y",
        folder="hackathon",
        tenant_id="tenant_y",
    )

    # Tenant X fetches clusters
    clusters_x = repo.get_all_face_clusters(tenant_id="tenant_x")
    cluster_ids_x = [c["cluster_id"] for c in clusters_x]
    assert "cluster_x_1" in cluster_ids_x
    assert "cluster_y_1" not in cluster_ids_x

    # Tenant Y fetches clusters
    clusters_y = repo.get_all_face_clusters(tenant_id="tenant_y")
    cluster_ids_y = [c["cluster_id"] for c in clusters_y]
    assert "cluster_y_1" in cluster_ids_y
    assert "cluster_x_1" not in cluster_ids_y


if __name__ == "__main__":
    import pathlib
    import tempfile

    print("[1/6] Running test_tenant_context_propagation...")
    test_tenant_context_propagation()
    print("      PASSED")

    print("[2/6] Running test_async_task_context_isolation...")
    asyncio.run(test_async_task_context_isolation())
    print("      PASSED")

    print("[3/6] Running test_jwt_tenant_claims...")
    test_jwt_tenant_claims()
    print("      PASSED")

    print("[4/6] Running test_faiss_tenant_partitioning...")
    with tempfile.TemporaryDirectory() as td:
        test_faiss_tenant_partitioning(pathlib.Path(td))
    print("      PASSED")

    print("[5/6] Running test_job_queue_tenant_idor_protection...")
    asyncio.run(test_job_queue_tenant_idor_protection())
    print("      PASSED")

    print("[6/6] Running test_repository_face_clusters_isolation...")
    test_repository_face_clusters_isolation()
    print("      PASSED")

    print("\n=======================================================")
    print("SUCCESS: ALL 6 PHASE 1 MULTI-TENANCY TESTS PASSED!")
    print("=======================================================")

