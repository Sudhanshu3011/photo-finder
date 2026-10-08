# Design Decisions: Why, What & How

This document explains the technical rationale behind every architectural decision, technology selection, and optimization implemented in the **Visual Search API**.

---

## 1. Why FAISS Instead of Hosted Cloud Vector Databases (Pinecone / Weaviate / Milvus Cloud)?

| Consideration | Cloud Vector DB (Pinecone / SaaS) | Local FAISS Engine (`src/modules/infra/faiss_engine.py`) |
| :--- | :--- | :--- |
| **Search Latency** | 50ms - 200ms per query (Network + TLS hop) | **< 2ms** (Direct in-memory SIMD dot product) |
| **Cost** | Monthly subscription fees + per-vector read/write charges | **$0.00** (Free, open-source C++ core) |
| **Data Privacy & Compliance** | Embeddings transmitted over external internet | **100% On-Premise / Local Container** |
| **Failure Modes** | Network timeouts, rate limiting, 429 quota exhaustion | **Zero external points of failure** |
| **Persistence** | Remote cloud storage | Stored as `.index` binary files on local disk |

### How It Was Implemented
- The vector engine uses native FAISS with `faiss.IndexFlatIP` (Inner Product on L2-normalized vectors), wrapped in `faiss.IndexIDMap2` to support arbitrary 64-bit integer IDs.
- For environments where native C++ compiled FAISS is unavailable, a vectorized NumPy fallback (`NumpyVectorIndex`) is automatically activated with the exact same API.
- All vector insertions immediately persist to `data/faiss/*.index` with atomic threading locks (`threading.RLock`).

---

## 2. Why SQLite Instead of Heavy External Databases (PostgreSQL / MongoDB)?

| Feature | PostgreSQL / MongoDB | SQLite (`data/local_storage.db`) |
| :--- | :--- | :--- |
| **Deployment Complexity** | Requires separate daemon, network setup, migrations | Single standalone file in container (`local_storage.db`) |
| **Connection Overhead** | TCP connection pool, handshake, network serialization | Zero-overhead in-process C function calls |
| **ACID Guarantees** | Yes | Yes (Full ACID compliance with WAL mode) |
| **Resource Footprint** | 300MB - 1GB idle RAM | < 5MB idle RAM |

### How It Was Implemented
- Fast metadata lookup for FAISS vectors via indexed integer IDs (`int_id`).
- Persistent user credential store with bcrypt password hashing.
- Lightweight KV cache (`kv_cache` table) replacing external Redis instances.
- Automated schema migrations in `init_db()` ensuring seamless column additions without manual migration scripts.
- Decoupled configuration via `SQLITE_DB_PATH` environment variable, enabling isolated test execution in `/tmp/test_local_storage.db` so test runs never touch production data.

---

## 3. Why Dual-Model Face Embeddings (ArcFace + AdaFace)?

### The Problem
Single-model face recognition often fails under challenging conditions:
- **ArcFace** is trained with additive angular margin loss. It excels on high-resolution, clear frontal faces but degrades when faces are partially obscured, blurry, or captured at extreme profile angles.
- **AdaFace** introduces an adaptive margin function based on image quality. It automatically relaxes margin penalties for low-quality or blurry faces, extracting robust embeddings where traditional models fail.

### The Solution: Score Fusion
```python
Fused Score = (0.60 * ArcFace_Similarity) + (0.40 * AdaFace_Similarity)
```
- By querying both indices and fusing scores with 60% ArcFace and 40% AdaFace weight, false positive rates drop dramatically while recall on blurry or angled surveillance crops increases significantly.
- If an input image is too degraded for AdaFace or if only ArcFace is available, the system gracefully falls back to solo ArcFace scoring without throwing errors.

---

## 4. Why HDBSCAN for Face Clustering Instead of K-Means or DBSCAN?

### Limitations of Alternative Algorithms
1. **K-Means**:
   - Requires knowing the exact number of people ($k$) beforehand—impossible in real-world photo galleries where the number of individuals is completely unknown.
   - Forces outlier faces (e.g. background faces) into nearest clusters, polluting identity albums.
2. **Standard DBSCAN**:
   - Relies on a single global distance threshold ($\epsilon$). In real photo libraries, density varies widely (some people appear in 100 photos under similar lighting, others appear in 5 photos across diverse environments).

### Why HDBSCAN (Hierarchical DBSCAN)
- Discovers clusters of varying densities across a hierarchical cluster tree.
- Automatically isolates outlier/unmatched faces into noise label (`-1`), preventing false identity merges.
- Requires only `min_cluster_size` (e.g., minimum 3 faces to declare a confirmed identity).
- Automatically calculates cluster medoids (the most representative frontal photo) for user album covers.

---

## 5. Why Cloudinary with Local Disk Staging?

- **Local Storage (`saved_images/`)**: Ensures immediate zero-latency decoding for OpenCV, AI inference, and quality checks.
- **Cloudinary CDN (`cloudinary_storage.py`)**: Provides instant global CDN delivery, automated responsive transformations, and permanent media backup.
- **Dual Pipeline Execution**: During batch ingestion, the system uploads to Cloudinary and runs AI inference simultaneously via `asyncio.gather()`, cutting ingestion wall-clock time in half.

