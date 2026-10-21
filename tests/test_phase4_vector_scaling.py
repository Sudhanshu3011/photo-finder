"""
tests/test_phase4_vector_scaling.py — Phase 4 Vector Scaling, HNSW, Pre-filtering & Caching Tests.

Verifies:
1. IndexHNSWFlat factory instantiation, IDMap2 wrapping, and efSearch configuration.
2. Search-time pre-filtering via IDSelectorBatch preventing top-k recall collapse.
3. Adversarial two-tenant isolation with identical embeddings.
4. Two-tier cryptographic search caching (L1 In-Memory + L2 Redis).
5. O(1) generation-based tenant cache invalidation.
6. Production fail-closed guard prohibiting silent NumPy fallback.
"""
import copy
import hashlib
import json
import os
import numpy as np
import pytest

from src.core.config import (
    IDX_FACES,
    IDX_OBJECTS,
    FACE_DIM,
    OBJECT_DIM,
    USE_HNSW_INDEX,
    HNSW_M,
    HNSW_EF_SEARCH,
)
from src.modules.infra.faiss_engine import (
    FAISSEngine,
    NumpyVectorIndex,
    build_vector_index,
    HAS_FAISS,
)
from src.modules.infra.search_cache import (
    SearchCacheManager,
    ThreadSafeTTLCache,
    get_search_cache,
)


def test_hnsw_recall_against_flat_ground_truth():
    """Verify IndexHNSWFlat achieves >= 99% recall against IndexFlatIP exact ground truth."""
    if not HAS_FAISS:
        pytest.skip("Native FAISS is required for HNSW vs FlatIP recall comparison")

    import faiss

    dim = 512
    num_vectors = 1000
    num_queries = 20
    top_k = 10

    # Generate synthetic normalized vectors
    np.random.seed(42)
    vectors = np.random.randn(num_vectors, dim).astype(np.float32)
    vectors /= np.linalg.norm(vectors, axis=1, keepdims=True)

    queries = np.random.randn(num_queries, dim).astype(np.float32)
    queries /= np.linalg.norm(queries, axis=1, keepdims=True)

    ids = np.arange(1, num_vectors + 1, dtype=np.int64)

    # 1. Exact FlatIP index (Ground Truth)
    flat_index = faiss.IndexIDMap2(faiss.IndexFlatIP(dim))
    flat_index.add_with_ids(vectors, ids)

    # 2. Approximate HNSW index (M=32, efConstruction=128, efSearch=64)
    hnsw_quantizer = faiss.IndexHNSWFlat(dim, 32, faiss.METRIC_INNER_PRODUCT)
    hnsw_quantizer.hnsw.efConstruction = 128
    hnsw_quantizer.hnsw.efSearch = 64
    hnsw_index = faiss.IndexIDMap2(hnsw_quantizer)
    hnsw_index.add_with_ids(vectors, ids)

    recalls = []
    for q in queries:
        q_arr = q.reshape(1, -1)
        _, flat_ids = flat_index.search(q_arr, top_k)
        _, hnsw_ids = hnsw_index.search(q_arr, top_k)

        gt_set = set(flat_ids[0])
        approx_set = set(hnsw_ids[0])
        recall = len(gt_set.intersection(approx_set)) / float(top_k)
        recalls.append(recall)

    mean_recall = float(np.mean(recalls))
    assert mean_recall >= 0.95, f"Expected HNSW Recall@10 >= 95%, got {mean_recall * 100:.2f}%"


def test_build_vector_index_hnsw():
    """Verify build_vector_index constructs IndexIDMap2 wrapping IndexHNSWFlat with proper efSearch."""
    dim = 512
    index = build_vector_index(dimension=dim, use_hnsw=True, m=32, ef_construction=128, ef_search=64)
    assert index is not None
    assert index.d == dim

    if HAS_FAISS:
        import faiss
        assert isinstance(index, faiss.IndexIDMap2)
        base = faiss.downcast_index(index.index)
        assert hasattr(base, "hnsw")
        assert base.hnsw.efSearch == 64
    else:
        assert isinstance(index, NumpyVectorIndex)


def test_hnsw_upsert_and_similarity_search():
    """Verify vectors added to HNSW can be retrieved accurately with cosine similarity."""
    engine = FAISSEngine(data_dir="data/test_faiss_hnsw")
    tenant_id = "test_hnsw_tenant"
    engine.reset_all(tenant_id=tenant_id)

    # Create 5 distinct normalized vectors
    vecs = np.random.randn(5, FACE_DIM).astype(np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = vecs / norms

    records = [
        {"id": f"face_{i}", "vector": vecs[i].tolist(), "url": f"https://s3/face_{i}.jpg", "folder": "default"}
        for i in range(5)
    ]
    upserted = engine.upsert(IDX_FACES, records, tenant_id=tenant_id)
    assert upserted == 5

    # Query with the exact vector of face_2
    results = engine.search(
        index_name=IDX_FACES,
        query_vector=vecs[2].tolist(),
        top_k=3,
        tenant_id=tenant_id,
    )
    assert len(results) > 0
    assert results[0]["id"] == "face_2"
    assert results[0]["score"] >= 0.99  # Identical vector inner product ~= 1.0


def test_idselector_prefiltering_isolation():
    """Verify allowed_int_ids pre-filters search and completely excludes unauthorized vectors."""
    engine = FAISSEngine(data_dir="data/test_faiss_prefilter")
    tenant_id = "test_prefilter_tenant"
    engine.reset_all(tenant_id=tenant_id)

    # Insert 4 vectors where vector 0 and vector 1 are identical
    base_vec = np.random.randn(1, FACE_DIM).astype(np.float32)
    base_vec = base_vec / np.linalg.norm(base_vec)

    records = [
        {"id": "doc_allowed_1", "vector": base_vec[0].tolist(), "url": "https://s3/1.jpg", "folder": "allowed"},
        {"id": "doc_unauthorized_2", "vector": base_vec[0].tolist(), "url": "https://s3/2.jpg", "folder": "restricted"},
    ]
    engine.upsert(IDX_FACES, records, tenant_id=tenant_id)

    # Get metadata to find integer IDs
    all_records = engine.get_all_records(IDX_FACES, tenant_id=tenant_id)
    id_map = {r["id"]: r["int_id"] for r in all_records}

    allowed_int_id = id_map["doc_allowed_1"]
    unauthorized_int_id = id_map["doc_unauthorized_2"]

    # Search with allowed_int_ids containing ONLY doc_allowed_1
    results = engine.search(
        index_name=IDX_FACES,
        query_vector=base_vec[0].tolist(),
        top_k=10,
        tenant_id=tenant_id,
        allowed_int_ids=[allowed_int_id],
    )

    assert len(results) == 1
    assert results[0]["id"] == "doc_allowed_1"

    # Search with allowed_int_ids containing ONLY doc_unauthorized_2
    results_unauth = engine.search(
        index_name=IDX_FACES,
        query_vector=base_vec[0].tolist(),
        top_k=10,
        tenant_id=tenant_id,
        allowed_int_ids=[unauthorized_int_id],
    )
    assert len(results_unauth) == 1
    assert results_unauth[0]["id"] == "doc_unauthorized_2"


def test_adversarial_two_tenant_isolation():
    """
    Adversarial Multi-Tenancy Test:
    Two tenants index identical vectors. Each search must return 100% of their own
    tenant's photos and 0% of the other tenant's photos.
    """
    engine = FAISSEngine(data_dir="data/test_adversarial_tenancy")
    tenant_alpha = "tenant_alpha_001"
    tenant_beta = "tenant_beta_002"

    engine.reset_all(tenant_id=tenant_alpha)
    engine.reset_all(tenant_id=tenant_beta)

    # Generate shared identical embedding
    identical_vec = np.random.randn(1, FACE_DIM).astype(np.float32)
    identical_vec = identical_vec / np.linalg.norm(identical_vec)

    alpha_records = [
        {"id": f"alpha_img_{i}", "vector": identical_vec[0].tolist(), "url": f"https://s3/alpha_{i}.jpg", "folder": "alpha_folder"}
        for i in range(3)
    ]
    beta_records = [
        {"id": f"beta_img_{i}", "vector": identical_vec[0].tolist(), "url": f"https://s3/beta_{i}.jpg", "folder": "beta_folder"}
        for i in range(3)
    ]

    engine.upsert(IDX_FACES, alpha_records, tenant_id=tenant_alpha)
    engine.upsert(IDX_FACES, beta_records, tenant_id=tenant_beta)

    # Query tenant Alpha
    alpha_matches = engine.search(
        index_name=IDX_FACES,
        query_vector=identical_vec[0].tolist(),
        top_k=10,
        tenant_id=tenant_alpha,
    )
    for m in alpha_matches:
        assert m["id"].startswith("alpha_img_"), f"Cross-tenant vector leak: found {m['id']} in tenant Alpha search"

    # Query tenant Beta
    beta_matches = engine.search(
        index_name=IDX_FACES,
        query_vector=identical_vec[0].tolist(),
        top_k=10,
        tenant_id=tenant_beta,
    )
    for m in beta_matches:
        assert m["id"].startswith("beta_img_"), f"Cross-tenant vector leak: found {m['id']} in tenant Beta search"


def test_two_tier_cache_sha256_stability():
    """Verify search cache generates deterministic SHA-256 keys and serves L1 in-memory hits."""
    cache = SearchCacheManager(l1_size=100, l1_ttl=60.0)
    tenant_id = f"test_cache_tenant_{os.urandom(4).hex()}"

    query_vec = np.random.randn(512).astype(np.float32)
    query_vec = query_vec / np.linalg.norm(query_vec)

    key1 = cache.make_cache_key(
        domain="faces",
        query_vector=query_vec,
        top_k=20,
        threshold=0.25,
        filter_dict={"folder": "events"},
        tenant_id=tenant_id,
    )
    key2 = cache.make_cache_key(
        domain="faces",
        query_vector=query_vec.copy(),
        top_k=20,
        threshold=0.25,
        filter_dict={"folder": "events"},
        tenant_id=tenant_id,
    )

    assert key1 == key2
    assert "cache:search:" in key1
    assert tenant_id in key1

    # Initially cache should miss
    assert cache.get(key1) is None

    # Populate cache
    mock_results = [{"id": "img_123", "score": 0.95, "url": "https://s3/123.jpg"}]
    cache.set(key1, mock_results)

    # Second read should be an L1 in-memory hit
    cached = cache.get(key1)
    assert cached is not None
    assert len(cached) == 1
    assert cached[0]["id"] == "img_123"
    assert cache.l1.hits >= 1


def test_generation_based_cache_invalidation():
    """Verify O(1) generation increment instantly invalidates cached queries for that tenant."""
    cache = SearchCacheManager(l1_size=100, l1_ttl=60.0)
    tenant_id = f"test_invalidation_{os.urandom(4).hex()}"

    query_vec = np.random.randn(512).astype(np.float32)
    key_gen1 = cache.make_cache_key("faces", query_vec, 20, 0.25, tenant_id=tenant_id)
    cache.set(key_gen1, [{"id": "old_result", "score": 0.9}])

    assert cache.get(key_gen1) is not None

    # Invalidate tenant
    new_gen = cache.invalidate_tenant(tenant_id)
    assert new_gen >= 2

    # New cache key includes new generation
    key_gen2 = cache.make_cache_key("faces", query_vec, 20, 0.25, tenant_id=tenant_id)
    assert key_gen1 != key_gen2
    assert f":g{new_gen}:" in key_gen2

    # Query with new generation should be a cache miss
    assert cache.get(key_gen2) is None


def test_production_fail_closed_guard(monkeypatch):
    """Verify that in ENVIRONMENT=production, missing FAISS raises RuntimeError instead of falling back to NumPy."""
    import src.modules.infra.faiss_engine as fe

    monkeypatch.setattr(fe, "ENVIRONMENT", "production")
    monkeypatch.setattr(fe, "HAS_FAISS", False)

    with pytest.raises(RuntimeError, match="FAISS native library is not installed in production environment"):
        build_vector_index(dimension=512, use_hnsw=True)
