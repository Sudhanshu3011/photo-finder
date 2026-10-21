"""
scripts/benchmark_vector_search.py — Stage 4.0 Vector Retrieval Benchmarking Harness.

Empirically benchmarks IndexFlatIP vs IndexHNSWFlat across:
1. Face Embeddings (512D)
2. Multimodal Scene Embeddings (1536D)
Measures Index Latency (P50, P95, P99), Index Build Throughput, and Recall@10.
"""
import argparse
import sys
import time
from typing import Dict, List, Tuple

import numpy as np

try:
    import faiss
except ImportError:
    print("ERROR: faiss package is required to run this benchmark.")
    sys.exit(1)


def generate_synthetic_vectors(num_vectors: int, dim: int) -> np.ndarray:
    """Generate L2-normalized float32 vectors."""
    vectors = np.random.randn(num_vectors, dim).astype(np.float32)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1e-12
    return vectors / norms


def benchmark_index(
    dim: int,
    dataset_size: int,
    num_queries: int = 100,
    top_k: int = 10,
    m: int = 32,
    ef_construction: int = 128,
    ef_search: int = 64,
) -> Dict[str, any]:
    """Benchmark FlatIP vs HNSWFlat for given dimensionality and dataset size."""
    print(f"\n{'='*70}")
    print(f"BENCHMARK: Dim={dim} | Dataset={dataset_size:,} | Queries={num_queries} | Top-K={top_k}")
    print(f"{'='*70}")

    vectors = generate_synthetic_vectors(dataset_size, dim)
    queries = generate_synthetic_vectors(num_queries, dim)
    ids = np.arange(1, dataset_size + 1, dtype=np.int64)

    # 1. Ground Truth: IndexFlatIP
    flat_quantizer = faiss.IndexFlatIP(dim)
    flat_index = faiss.IndexIDMap2(flat_quantizer)

    t0 = time.perf_counter()
    flat_index.add_with_ids(vectors, ids)
    flat_build_time = time.perf_counter() - t0

    flat_latencies: List[float] = []
    flat_results: List[np.ndarray] = []
    for q in queries:
        q_arr = q.reshape(1, -1)
        t_start = time.perf_counter()
        scores, match_ids = flat_index.search(q_arr, top_k)
        flat_latencies.append((time.perf_counter() - t_start) * 1000.0)
        flat_results.append(match_ids[0])

    flat_p50 = float(np.percentile(flat_latencies, 50))
    flat_p95 = float(np.percentile(flat_latencies, 95))
    flat_p99 = float(np.percentile(flat_latencies, 99))

    # 2. Candidate: IndexHNSWFlat
    hnsw_quantizer = faiss.IndexHNSWFlat(dim, m, faiss.METRIC_INNER_PRODUCT)
    hnsw_quantizer.hnsw.efConstruction = ef_construction
    hnsw_quantizer.hnsw.efSearch = ef_search
    hnsw_index = faiss.IndexIDMap2(hnsw_quantizer)

    t0 = time.perf_counter()
    hnsw_index.add_with_ids(vectors, ids)
    hnsw_build_time = time.perf_counter() - t0

    hnsw_latencies: List[float] = []
    recalls: List[float] = []
    for idx, q in enumerate(queries):
        q_arr = q.reshape(1, -1)
        t_start = time.perf_counter()
        scores, match_ids = hnsw_index.search(q_arr, top_k)
        hnsw_latencies.append((time.perf_counter() - t_start) * 1000.0)

        # Calculate Recall@K vs Flat ground truth
        gt_set = set(flat_results[idx])
        found_set = set(match_ids[0])
        recall = len(gt_set.intersection(found_set)) / float(top_k)
        recalls.append(recall)

    hnsw_p50 = float(np.percentile(hnsw_latencies, 50))
    hnsw_p95 = float(np.percentile(hnsw_latencies, 95))
    hnsw_p99 = float(np.percentile(hnsw_latencies, 99))
    mean_recall = float(np.mean(recalls)) * 100.0

    speedup = flat_p95 / max(hnsw_p95, 0.001)

    print(f"FlatIP:   Build={flat_build_time:.2f}s | P50={flat_p50:.3f}ms | P95={flat_p95:.3f}ms | P99={flat_p99:.3f}ms")
    print(f"HNSWFlat: Build={hnsw_build_time:.2f}s | P50={hnsw_p50:.3f}ms | P95={hnsw_p95:.3f}ms | P99={hnsw_p99:.3f}ms")
    print(f"Accuracy: Recall@{top_k} = {mean_recall:.2f}% | P95 Speedup = {speedup:.1f}x")

    return {
        "dim": dim,
        "dataset_size": dataset_size,
        "flat_p95_ms": flat_p95,
        "hnsw_p95_ms": hnsw_p95,
        "speedup_x": speedup,
        "recall_at_k": mean_recall,
    }


def main():
    parser = argparse.ArgumentParser(description="FAISS HNSW Vector Search Benchmark")
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 50000], help="Dataset sizes to benchmark")
    parser.add_argument("--queries", type=int, default=50, help="Number of query evaluations")
    parser.add_argument("--m", type=int, default=32, help="HNSW graph links per node")
    parser.add_argument("--ef-search", type=int, default=64, help="HNSW search depth")
    args = parser.parse_args()

    results = []
    for size in args.sizes:
        # Benchmark Face Vectors (512D)
        res_face = benchmark_index(
            dim=512,
            dataset_size=size,
            num_queries=args.queries,
            m=args.m,
            ef_search=args.ef_search,
        )
        results.append(res_face)

        # Benchmark Scene Vectors (1536D)
        res_scene = benchmark_index(
            dim=1536,
            dataset_size=size,
            num_queries=args.queries,
            m=args.m,
            ef_search=args.ef_search,
        )
        results.append(res_scene)

    print(f"\n{'='*70}")
    print("SUMMARY RESULTS")
    print(f"{'='*70}")
    for r in results:
        print(f"Dim {r['dim']:4d} | N={r['dataset_size']:6,d} | Recall@10={r['recall_at_k']:6.2f}% | "
              f"Flat P95={r['flat_p95_ms']:6.3f}ms | HNSW P95={r['hnsw_p95_ms']:6.3f}ms | Speedup={r['speedup_x']:4.1f}x")


if __name__ == "__main__":
    main()

