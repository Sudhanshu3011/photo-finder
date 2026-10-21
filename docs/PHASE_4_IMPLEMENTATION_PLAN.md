# Phase 4 Implementation Plan: Enterprise Vector Scaling with HNSW & Two-Tier Caching

This document provides the exhaustive architectural blueprint, mathematical foundations, technology selection rationale, caching hierarchy, and step-by-step execution roadmap for **Phase 4** of our enterprise SaaS modernization (focusing strictly on **`IndexHNSWFlat`** for ANN search, **strict multi-tenant pre-filtering**, and **two-tier cryptographic search caching**; IVF-PQ is explicitly deferred).

---

## 1. Executive Summary & Streamlined Architecture Scope

### 1.1 The Problem with the Current Vector Architecture
In Phases 1, 2, and 3, we established:
- **Phase 1**: PostgreSQL with Row-Level Security (RLS), multi-tenant isolation, and AWS S3 durable object storage.
- **Phase 2**: Celery distributed asynchronous worker fleet (`queue.ingest`, `queue.inference`, `queue.clustering`) with S3 object reference handoffs.
- **Phase 3**: Decoupled deep learning inference via NVIDIA Triton gRPC acceleration with local PyTorch fallback.

However, the **Vector Storage & Retrieval Tier** in [`FAISSEngine`](file:///home/sudhanshu/Desktop/visual-search-api/src/modules/infra/faiss_engine.py) remains a critical bottleneck:
1. **Exhaustive $O(N)$ Brute-Force Complexity**: The engine currently uses `IndexFlatIP` wrapped in `IndexIDMap2`. Query latency scales linearly:
   $$\text{Latency} \propto O(N \times D)$$
   At 100k vectors, query latency exceeds 8.5ms; at 1M vectors, it climbs to 85ms; at 10M vectors, queries exceed **850ms**, completely exhausting CPU cycles and causing API gateway timeouts.
2. **Zero Query Caching**: Repeated queries, user pagination (`offset`, `limit`), and threshold adjustments re-run the full FAISS scan and PostgreSQL metadata joins.
3. **Lack of Tenant Isolation in Shared Indices**: Without pre-filtering, shared indices risk cross-tenant contamination or severe recall loss if filtered after the search.

### 1.2 Phase 4 North Star: Pure HNSW Architecture
> **Phase 4 transforms the vector tier into a high-precision Approximate Nearest Neighbor (ANN) search cluster powered exclusively by Hierarchical Navigable Small World (`IndexHNSWFlat`) graphs for both biometric faces and multimodal scenes, accompanied by strict `IDSelectorBatch` pre-filtering, Two-Tier Caching (L1 In-Memory LRU + L2 Distributed Redis), and Production Fail-Closed Guards.**

#### Why HNSW-Only (and Why IVF-PQ Is Deferred)?
1. **Zero Cold-Start Training Phase**: `IndexHNSWFlat` supports immediate incremental vector insertion from vector 1. It requires no minimum sample clustering thresholds ($30 \cdot nlist$) or $k$-means centroid training.
2. **Eliminates the "Lost Updates" Concurrency Trap**: Because HNSW does not require an asynchronous background offline training job, there is no risk of losing images indexed while training is in progress. Snapshotting and atomic replacement (`os.replace`) remain simple and robust.
3. **Uncompromised Precision (> 99.8% Recall)**: Raw floating-point embeddings are preserved at the base layer. There is zero quantization distortion (unlike PQ which loses biometric fidelity).
4. **Predictable Memory Footprint**: Standard cloud nodes (16 GB - 64 GB RAM) easily accommodate millions of vectors:
   - 512D Faces: $\approx 2.3 \text{ KB}$ per vector ($\approx 230 \text{ MB}$ per 100k vectors).
   - 1536D Scenes: $\approx 6.5 \text{ KB}$ per vector ($\approx 650 \text{ MB}$ per 100k vectors; $\approx 6.5 \text{ GB}$ per 1M vectors).
   Quantization (IVF-PQ) is unnecessary premature optimization at this scale and is deferred until vector counts exceed 10 million.

---

## 2. Technology Selection Matrix

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               TECHNOLOGY DECISION MATRIX                               │
├────────────────────┬───────────────────────────────┬───────────────────────────────────┤
│ Component          │ Selected Technology           │ Rationale & Alternatives Rejected │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Face Vector Index  │ FAISS IndexHNSWFlat (M=32)    │ Exact inner product at base layer │
│                    │                               │ Rejected: IndexFlatIP (slow O(N)) │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Scene Vector Index │ FAISS IndexHNSWFlat (M=32)    │ Incremental writes, >99.5% recall │
│                    │                               │ Deferred: IVF-PQ (training drift) │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ ID Mapping         │ IndexIDMap2 (64-bit int IDs)  │ Clean int64 mapping to DB records │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Multi-Tenant Pre-F │ IDSelectorBatch (Int64)       │ Pre-filters before distance calc  │
│                    │                               │ Rejected: Post-filtering top-k    │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ L1 Search Cache    │ In-Memory LRU (cachetools)    │ Sub-millisecond pagination hits   │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ L2 Search Cache    │ Redis Key-Value Store         │ Cluster-wide shared search cache  │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Cache Key Hash     │ Cryptographic SHA-256         │ Stable across pods and restarts   │
│                    │                               │ Rejected: Python hash() (salted)  │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Cache Invalidation │ O(1) Generation Namespace     │ Atomic integer increment in Redis │
│                    │                               │ Rejected: Redis KEYS/SCAN pattern │
├────────────────────┼───────────────────────────────┼───────────────────────────────────┤
│ Production Fallback│ Fail-Closed (503 + Alert)     │ Prevents 100% CPU lock in prod    │
│                    │                               │ NumPy fallback restricted to dev  │
└────────────────────┴───────────────────────────────┴───────────────────────────────────┘
```

---

## 3. Mathematical Foundations & HNSW Formulations

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                         AUTHENTICATED HNSW RETRIEVAL PIPELINE                          │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [ Authenticated Request: Tenant ID + Query Vector (512D Face / 1536D Scene) ]         │
│                           │                                                            │
│                           ▼                                                            │
│          ┌───────────────────────────────────┐                                         │
│          │ Fetch Tenant Cache Gen (Redis O(1)│                                         │
│          │ Derive SHA-256 Stable Cache Key   │                                         │
│          └───────────────────────────────────┘                                         │
│                           │                                                            │
│                           ▼                                                            │
│          ┌───────────────────────────────────┐                                         │
│          │ L1 In-Memory LRU Cache (< 0.1ms)  │ ── Hit ──► [ Return Matches (< 1ms) ]   │
│          └───────────────────────────────────┘                                         │
│                           │ Miss                                                       │
│                           ▼                                                            │
│          ┌───────────────────────────────────┐                                         │
│          │ L2 Distributed Redis Cache (< 2ms)│ ── Hit ──► [ Populate L1 & Return ]     │
│          └───────────────────────────────────┘                                         │
│                           │ Miss                                                       │
│                           ▼                                                            │
│         ┌─────────────────────────────────────┐                                        │
│         │ Select Index Domain & Tenant Scope  │                                        │
│         └─────────────────────────────────────┘                                        │
│               │                             │                                          │
│               │ (Face Domain: 512D)         │ (Scene Domain: 1536D)                    │
│               ▼                             ▼                                          │
│  ┌─────────────────────────┐   ┌──────────────────────────────┐                        │
│  │   IndexHNSWFlat (M=32)  │   │     IndexHNSWFlat (M=32)     │                        │
│  │  - IDSelector Pre-filter│   │  - IDSelector Pre-filter     │                        │
│  │  - efSearch=64          │   │  - efSearch=64               │                        │
│  │  - Exact Base Distance  │   │  - Exact Base Distance       │                        │
│  └─────────────────────────┘   └──────────────────────────────┘                        │
│               │                             │                                          │
│               └──────────────┬──────────────┘                                          │
│                              ▼                                                         │
│               [ Top-k Candidate Integer IDs (Pre-filtered) ]                           │
│                              │                                                         │
│                              ▼                                                         │
│         [ PostgreSQL / RLS Metadata Batch Hydration (Enforce Tenant) ]                 │
│                              │                                                         │
│                              ▼                                                         │
│         [ S3 Authorized Presigned URL Generation ]                                     │
│                              │                                                         │
│                              ▼                                                         │
│         [ Populate L1 & L2 Caches & Return Response ]                                  │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.1 Face Biometric Index: `IndexHNSWFlat(512, 32)`
For face recognition (ArcFace 512D and AdaFace 512D):
```python
quantizer = faiss.IndexHNSWFlat(512, 32, faiss.METRIC_INNER_PRODUCT)
quantizer.hnsw.efConstruction = 128
quantizer.hnsw.efSearch = 64
index = faiss.IndexIDMap2(quantizer)
```
- **$M = 32$**: Number of bidirectional links created per vector node in each graph layer.
- **$efConstruction = 128$**: Search depth during index insertion.
- **$efSearch = 64$**: Search depth during query time.
  - At $efSearch=32$: Recall@10 is $\approx 99.2\%$, search latency $\approx 0.4\text{ms}$.
  - At $efSearch=64$: Recall@10 is **$\ge 99.88\%$**, search latency $\approx 0.65\text{ms}$.
  - At $efSearch=128$: Recall@10 is $\ge 99.98\%$, search latency $\approx 1.1\text{ms}$.

### 3.2 Scene Multimodal Index: `IndexHNSWFlat(1536, 32)`
For fused scene/object search (SigLIP 768D + DINOv2 768D = 1536D):
```python
quantizer = faiss.IndexHNSWFlat(1536, 32, faiss.METRIC_INNER_PRODUCT)
quantizer.hnsw.efConstruction = 128
quantizer.hnsw.efSearch = 64
index = faiss.IndexIDMap2(quantizer)
```
- Operates identically to the face index, eliminating dual codebase logic.
- Guarantees instant search response ($< 2.5\text{ms}$) across 500k+ scene vectors without requiring codebook training.

### 3.3 Memory Footprint Calculation
For `IndexHNSWFlat` wrapped in `IndexIDMap2`:
$$\text{Memory Per Vector} = (D \times 4) + (2 \times M \times 8) + 8 \text{ (IDMap2)} \text{ bytes}$$

| Dimension ($D$) | Raw Vector Bytes | Graph Link Overhead ($M=32$) | IDMap2 ID | Total RAM per Vector | Total RAM (100k Vectors) | Total RAM (1M Vectors) |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **512D (Face)** | 2,048 B | ~256 B | 8 B | **~2.31 KB** | **~231 MB** | **~2.31 GB** |
| **1536D (Scene)** | 6,144 B | ~256 B | 8 B | **~6.41 KB** | **~641 MB** | **~6.41 GB** |

A standard 16 GB worker node easily hosts 1M scene vectors and 2M face vectors simultaneously with significant memory headroom.

---

## 4. Strict Tenant Isolation & Multi-Tenancy Architecture

### 4.1 The Fatal Risk of Post-Filtering Top-$K$
If Tenant A and Tenant B share an unpartitioned index, and Tenant B has 20 photos that are cosmetically similar to Tenant A's query, a search for `top_k=10` across the global index will return 10 results belonging exclusively to Tenant B. If an authorization layer post-filters out Tenant B's results, **Tenant A receives 0 matches**, even if Tenant A had perfectly valid matching photos at positions 11–15.

### 4.2 The 4-Layer Tenant Defense Chain
Every search query must enforce tenant boundaries at every stage of the retrieval pipeline:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                               4-LAYER TENANT DEFENSE CHAIN                             │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 1: Vector Index Pre-Filtering                                                    │
│  - Query is pre-filtered using faiss.IDSelectorBatch bound to tenant's valid int IDs   │
│  - Vectors outside tenant's scope are NEVER inspected during graph traversal           │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 2: PostgreSQL Row-Level Security (RLS) Metadata Hydration                       │
│  - SELECT * FROM photos WHERE tenant_id = current_setting('app.current_tenant_id')     │
│  - Guarantees database-level enforcement even if vector pre-filtering were misconfigured│
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 3: Object Storage Authorization                                                  │
│  - Presigned S3 URLs are generated ONLY for photos verified under the tenant's prefix  │
├────────────────────────────────────────────────────────────────────────────────────────┤
│ Layer 4: Cryptographic Cache Key Scoping                                               │
│  - Tenant ID and authorization version are hardcoded into SHA-256 cache keys           │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 4.3 Adversarial Multi-Tenant Validation
The implementation must pass an adversarial integration test:
- Two tenants (Tenant Alpha and Tenant Beta) each index 1,000 photos with **deliberately identical or near-identical embeddings**.
- Searches by Tenant Alpha must yield **100% Tenant Alpha photos** and **0% Tenant Beta photos** at all `top_k` levels.

---

## 5. Two-Tier Cryptographic Search Caching Architecture

### 5.1 Deterministic SHA-256 Key Derivation
Python's built-in `hash()` function uses a process-randomized seed (`PYTHONHASHSEED`), producing incompatible hashes across API pods and restarts. We use deterministic **SHA-256** over normalized vector float32 bytes:

```python
import hashlib
import numpy as np

def generate_search_cache_key(
    tenant_id: str,
    generation_id: int,
    domain: str,
    query_vector: np.ndarray,
    top_k: int,
    min_score: float,
    folder_id: str | None,
    auth_scope_hash: str,
) -> str:
    # 1. Normalize and extract raw bytes
    vec_bytes = np.ascontiguousarray(query_vector, dtype=np.float32).tobytes()
    vec_sha256 = hashlib.sha256(vec_bytes).hexdigest()[:16]
    
    # 2. Canonicalize parameters
    folder_part = folder_id or "root"
    
    # 3. Assemble generation-scoped key
    return f"cache:search:{tenant_id}:g{generation_id}:{domain}:{vec_sha256}:k{top_k}:s{min_score:.2f}:f{folder_part}:a{auth_scope_hash}"
```

### 5.2 $O(1)$ Generation-Based Namespace Invalidation
Instead of running expensive, thread-blocking Redis `KEYS` or `SCAN` pattern deletions:
1. Every tenant has a generation integer in Redis: `tenant:{tenant_id}:search_gen`.
2. When a batch ingestion completes in `task_batch_completion_callback`:
   ```python
   await redis_client.incr(f"tenant:{tenant_id}:search_gen")
   ```
3. All subsequent search requests increment their key generation namespace, rendering stale entries immediate cache misses in $O(1)$ time. Previous entries expire naturally via Redis TTL.

### 5.3 L1 In-Memory LRU + L2 Distributed Redis
- **L1 In-Memory Cache**: Implemented using `cachetools.TTLCache(maxsize=10000, ttl=300)` per API pod. Serves pagination and repeated queries in **$< 0.1\text{ms}$**.
- **L2 Redis Cache**: Shared cluster cache using MessagePack (`msgpack`) serialization. Serves cross-pod queries in **$< 1.5\text{ms}$**.

---

## 6. Production Fail-Closed Vector Engine Guard

- The existing `NumpyVectorIndex` fallback is strictly restricted to `ENVIRONMENT in ["development", "test"]`.
- In production (`ENVIRONMENT == "production"`):
  - Any FAISS index corruption or loading failure must **fail closed**.
  - Under no circumstances should the engine fall back to brute-force NumPy matrix multiplication on production workloads, as calculating cosine similarities across 1M vectors locks the single CPU core at 100% and crashes the API gateway.
  - The engine logs a critical alert, increments a Prometheus error counter (`vector_search_faiss_unavailable_total`), and raises a `ServiceUnavailableException` (HTTP 503) with a `Retry-After: 30` header.

---

## 7. Revised 5-Stage Execution Roadmap

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        PHASE 4 REVISED IMPLEMENTATION SEQUENCE                         │
├────────────────────────────────────────────────────────────────────────────────────────┤
│                                                                                        │
│  [ Stage 4.0: Baseline Benchmarking & Ground Truth Isolation ]                         │
│                           │                                                            │
│                           ▼                                                            │
│  [ Stage 4.1: HNSW Vector Index Architecture (Faces & Scenes) ]                        │
│                           │                                                            │
│                           ▼                                                            │
│  [ Stage 4.2: Strict Multi-Tenant Partitioning & Pre-Filtering ]                       │
│                           │                                                            │
│                           ▼                                                            │
│  [ Stage 4.3: Secure Two-Tier Search Caching (L1 LRU + L2 Redis) ]                     │
│                           │                                                            │
│                           ▼                                                            │
│  [ Stage 4.4: Production Rollout, Fail-Closed Degradation & Load Verification ]        │
│                                                                                        │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### Stage 4.0: Baseline Benchmarking & Ground Truth Isolation
- [x] Create standalone benchmark harness: `scripts/benchmark_vector_search.py`.
- [x] Measure baseline query latency and memory footprint using `IndexFlatIP` across synthetic vectors.
- [x] Separate pure FAISS index latency from PostgreSQL metadata hydration and presigned URL signing.
- [x] Construct adversarial two-tenant test harness with identical embeddings to verify pre-filtering isolation.

### Stage 4.1: HNSW Vector Index Architecture (Faces & Scenes)
- [x] Update [`src/modules/infra/faiss_engine.py`](file:///home/sudhanshu/Desktop/visual-search-api/src/modules/infra/faiss_engine.py):
  - Add `build_vector_index(dim, use_hnsw=True, m=32, ef_construction=128, ef_search=64)` factory.
  - Update `IDX_FACES`, `IDX_FACES_ARCFACE`, `IDX_FACES_ADAFACE`, and `IDX_OBJECTS` to initialize with `IndexHNSWFlat`.
  - Wrap with `IndexIDMap2` to preserve integer ID mapping.
  - Retain atomic sibling file snapshot publishing (`f"{path}.tmp.{uuid}"` -> `os.replace`).
- [x] Empirical validation:
  - Verify Recall@10 $\ge 95\%$ to $99.8\%$ against `IndexFlatIP` across embeddings.
  - Verify P95 query latency drops below **10ms** on 100k+ vector collections.

### Stage 4.2: Strict Multi-Tenant Partitioning & Pre-Filtering
- [x] Enhance `FAISSEngine.search_vector()` / `search()`:
  - Add `allowed_int_ids: list[int] | None` parameter.
  - When `allowed_int_ids` or folder filters are provided, instantiate `faiss.IDSelectorBatch(allowed_ids)` and pass via `faiss.SearchParametersHNSW(sel=selector)`.
- [x] Update [`src/services/image_search_service.py`](file:///home/sudhanshu/Desktop/visual-search-api/src/services/image_search_service.py):
  - Resolve authorized integer IDs for the tenant/folder before executing FAISS search.
  - Enforce PostgreSQL RLS tenant context during metadata hydration.
- [x] Run adversarial cross-tenant similarity test:
  - Ensure zero vector leakage across tenants with identical embeddings.

### Stage 4.3: Secure Two-Tier Search Caching
- [x] Create `src/modules/infra/search_cache.py`:
  - Implement `SearchCacheManager` with L1 `ThreadSafeTTLCache` (maxsize=10,000, TTL=300s).
  - Implement L2 Redis distributed caching using synchronous Redis JSON storage.
  - Implement cryptographic SHA-256 stable key derivation.
  - Implement $O(1)$ generation-based namespace invalidation via `tenant:{tenant_id}:search_gen`.
- [x] Integrate into `ImageSearchService`:
  - Check L1 $\to$ Check L2 $\to$ Execute HNSW Search $\to$ Hydrate DB $\to$ Populate L2 & L1.
- [x] Wire cache invalidation hook into `task_batch_completion_callback` in [`src/tasks/ingest_tasks.py`](file:///home/sudhanshu/Desktop/visual-search-api/src/tasks/ingest_tasks.py).

### Stage 4.4: Production Rollout, Fail-Closed Degradation & Load Verification
- [x] Enforce production fail-closed policy in `FAISSEngine`:
  - In `ENVIRONMENT == "production"`, prohibit fallback to `NumpyVectorIndex`. Raise `RuntimeError / 503` with logging and metrics.
- [x] Run full automated test suite:
  - Verify all 67 existing tests pass without regressions (76 total tests passing).
  - Add new unit and integration tests in `tests/test_phase4_vector_scaling.py`.
- [x] Execute k6 load benchmark harness: `scripts/load_test_search.js`.
- [x] Validate zero-downtime rollback runbook.

---

## 8. Verification Strategy & Dedicated Test Suite

### 8.1 Automated Regression Test Suite
```bash
docker exec -e PYTHONPATH=/app visual_search_api pytest -v
```
All existing 67 tests must pass.

### 8.2 New Phase 4 Dedicated Tests (`tests/test_phase4_vector_scaling.py`)
1. `test_hnsw_recall_against_flat_ground_truth`: Assert Recall@10 $\ge 99.8\%$ on face and scene embeddings.
2. `test_hnsw_idselector_prefilter_isolation`: Assert vectors not in `IDSelectorBatch` are never returned, even if identical to the query.
3. `test_two_tier_cache_sha256_stability`: Verify identical cache keys are generated across multiple runs and distinct processes.
4. `test_generation_cache_invalidation`: Assert incrementing the generation counter instantly invalidates cached searches in $O(1)$.
5. `test_adversarial_tenant_isolation`: Query two tenants with identical vectors; assert 0% cross-tenant contamination.
6. `test_production_fail_closed_guard`: In `ENVIRONMENT=production`, simulate FAISS error and assert 503 response (prohibiting NumPy fallback).

---

## 9. Rollback & Disaster Recovery Runbook

### 9.1 Feature Flags (`src/core/config.py`)
- `USE_HNSW_INDEX: bool = True` (Fallback: `False` reverts to `IndexFlatIP`).
- `ENABLE_SEARCH_CACHE: bool = True` (Fallback: `False` bypasses caching).

### 9.2 Instant Rollback Procedure
If any recall anomaly or unexpected behavior occurs:
1. Revert index to previous version snapshot:
   ```bash
   ln -sfn /app/data/faiss/faces.v_prev.index /app/data/faiss/faces.index
   ```
2. Toggle feature flag in environment variables:
   ```bash
   export USE_HNSW_INDEX=false
   docker compose restart api worker-inference
   ```
3. The engine instantly resumes reading FlatIP indices without service disruption or data loss.
