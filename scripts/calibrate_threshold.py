"""
Threshold calibration tool.

Use this to find the FACE_MATCH_THRESHOLD that gives you the best
precision/recall tradeoff for YOUR specific data. Default 0.28 is an
industry-average — your data may differ.

Usage:
    1. Build two test sets:
       - POSITIVE_PAIRS: pairs of (query_image, gallery_image) of the SAME person
       - NEGATIVE_PAIRS: pairs of DIFFERENT people (hard negatives help most)

    2. Populate TEST_PAIRS below with local image paths

    3. Run: python scripts/calibrate_threshold.py

Output: table of thresholds with TP/FP/FN/precision/recall/F1.
"""
import sys
import os
from pathlib import Path

# Add project root to path so `src.*` imports work when running from scripts/
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from PIL import Image


# ── EDIT THESE ──────────────────────────────────────────────
# Each tuple: (path_to_query_image, path_to_gallery_image, is_same_person)
TEST_PAIRS = [
    # Example positives (same person, different photos)
    # ("test_data/alice_1.jpg", "test_data/alice_2.jpg", True),
    # ("test_data/alice_1.jpg", "test_data/alice_3.jpg", True),
    # ("test_data/bob_1.jpg", "test_data/bob_2.jpg", True),

    # Example hard negatives (different people, similar looking)
    # ("test_data/alice_1.jpg", "test_data/carol_1.jpg", False),
    # ("test_data/bob_1.jpg", "test_data/dave_1.jpg", False),
]
# ────────────────────────────────────────────────────────────


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


def compute_pair_scores():
    """Returns list of (fused_score, arcface_score, adaface_score, is_positive)."""
    from src.services.ai_manager import AIModelManager
    print("Loading models...")
    ai = AIModelManager()

    results = []
    for query_path, gallery_path, is_positive in TEST_PAIRS:
        if not (os.path.exists(query_path) and os.path.exists(gallery_path)):
            print(f"  Skipping missing: {query_path} or {gallery_path}")
            continue

        with open(query_path, "rb") as f:
            q_vectors = ai.process_image_bytes(f.read(), detect_faces=True)
        with open(gallery_path, "rb") as f:
            g_vectors = ai.process_image_bytes(f.read(), detect_faces=True)

        q_faces = [v for v in q_vectors if v["type"] == "face"]
        g_faces = [v for v in g_vectors if v["type"] == "face"]

        if not q_faces or not g_faces:
            print(f"  No face in: {query_path} or {gallery_path}")
            continue

        # Take largest face from each
        qf = max(q_faces, key=lambda f: f.get("face_width_px", 0))
        gf = max(g_faces, key=lambda f: f.get("face_width_px", 0))

        arc_score = cosine(qf["arcface_vector"], gf["arcface_vector"])
        if qf.get("has_adaface") and gf.get("has_adaface"):
            ada_score = cosine(qf["adaface_vector"], gf["adaface_vector"])
        else:
            ada_score = 0.15

        fused = 0.6 * arc_score + 0.4 * ada_score

        results.append({
            "query": query_path,
            "gallery": gallery_path,
            "is_positive": is_positive,
            "arcface": arc_score,
            "adaface": ada_score,
            "fused": fused,
        })

        tag = "SAME" if is_positive else "DIFF"
        print(f"  [{tag}] arc={arc_score:.3f} ada={ada_score:.3f} fused={fused:.3f}")

    return results


def evaluate_thresholds(results):
    """Sweep thresholds and compute P/R/F1 for each."""
    if not results:
        print("\nNo results to evaluate. Add pairs to TEST_PAIRS above.")
        return

    print("\n" + "=" * 78)
    print(f"{'arcface_thr':<14}{'fused_thr':<14}{'TP':>6}{'FP':>6}{'FN':>6}"
          f"{'Precision':>12}{'Recall':>10}{'F1':>8}")
    print("=" * 78)

    n_positive = sum(1 for r in results if r["is_positive"])

    best = {"f1": 0, "arc_thr": 0, "fused_thr": 0}

    for arc_thr in [0.20, 0.24, 0.28, 0.32, 0.36, 0.40, 0.45]:
        for fused_thr in [0.22, 0.26, 0.30, 0.34, 0.38]:
            tp = fp = fn = 0
            for r in results:
                # A match passes both thresholds
                predicted_match = (r["arcface"] >= arc_thr and r["fused"] >= fused_thr)
                if r["is_positive"]:
                    if predicted_match:
                        tp += 1
                    else:
                        fn += 1
                else:
                    if predicted_match:
                        fp += 1
            precision = tp / (tp + fp) if (tp + fp) else 0
            recall = tp / (tp + fn) if (tp + fn) else 0
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0

            if f1 > best["f1"]:
                best = {"f1": f1, "arc_thr": arc_thr, "fused_thr": fused_thr,
                        "tp": tp, "fp": fp, "fn": fn,
                        "precision": precision, "recall": recall}

            print(f"{arc_thr:<14.2f}{fused_thr:<14.2f}{tp:>6}{fp:>6}{fn:>6}"
                  f"{precision:>12.3f}{recall:>10.3f}{f1:>8.3f}")

    print("=" * 78)
    print(f"\nBest F1: {best['f1']:.3f}")
    print(f"  FACE_MATCH_THRESHOLD = {best['arc_thr']}")
    print(f"  FUSED_MATCH_THRESHOLD = {best['fused_thr']}")
    print(f"  Precision = {best['precision']:.3f}, Recall = {best['recall']:.3f}")
    print("\nUpdate these in your HF Space env vars.")


if __name__ == "__main__":
    if not TEST_PAIRS:
        print("Edit scripts/calibrate_threshold.py and populate TEST_PAIRS with")
        print("10-30 positive pairs and 10-30 hard-negative pairs, then re-run.")
        print("\nTip: export ~50 face photos from your own gallery, hand-label")
        print("the same-person pairs, and use those for calibration.")
        sys.exit(1)

    results = compute_pair_scores()
    evaluate_thresholds(results)