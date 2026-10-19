"""
tests/test_phase2_celery_workers.py — Integration and Unit Tests for Phase 2 Celery Worker Fleet.
Tests queue routing topology, tenant context propagation in Celery tasks,
image deduplication (SHA256 & pHash), durable S3 object references (cross-pod execution),
atomic multi-counter telemetry, and outcome-aware batch completion callbacks.
"""
import io
import pytest
from unittest.mock import MagicMock, patch
from PIL import Image

from celery_app import app as celery_app
from src.core.tenant_context import (
    DEFAULT_TENANT_ID,
    get_current_tenant_id,
    set_current_tenant_id,
    reset_tenant_context,
)
from src.modules.deduplication.image_hasher import (
    compute_sha256,
    compute_phash,
    hamming_distance,
    is_perceptual_duplicate,
    find_duplicate_image,
)
from src.tasks.base import (
    TenantAwareTask,
    record_task_outcome,
    sync_job_progress_increment,
)
from src.tasks.ingest_tasks import (
    task_process_image_upload,
    task_batch_completion_callback,
)
from src.tasks.inference_tasks import task_extract_embeddings
from src.tasks.clustering_tasks import task_run_face_clustering


# Helper to generate test JPEG bytes with pattern gradients
def make_test_image(width: int = 120, height: int = 120, pattern: str = "gradient", color=None) -> bytes:
    if color is not None:
        img = Image.new("RGB", (width, height), color=color)
    else:
        img = Image.new("RGB", (width, height))
        pixels = img.load()
        for y in range(height):
            for x in range(width):
                if pattern == "gradient":
                    pixels[x, y] = (int(x * 255 / width), int(y * 255 / height), 128)
                elif pattern == "stripes":
                    val = 255 if (x // 8) % 2 == 0 else 0
                    pixels[x, y] = (val, val, val)
                else:
                    pixels[x, y] = (int((x + y) * 128 / (width + height)), 50, 200)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def test_celery_queue_routing_and_reliability_settings():
    """Verify Celery app routing rules, serialization, and late acknowledgements."""
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.task_serializer == "json"

    # Verify task queue mapping
    routes = conf.task_routes
    assert routes["src.tasks.ingest_tasks.*"]["queue"] == "queue.ingest"
    assert routes["src.tasks.inference_tasks.*"]["queue"] == "queue.inference"
    assert routes["src.tasks.clustering_tasks.*"]["queue"] == "queue.clustering"


def test_tenant_context_propagation_in_celery_task():
    """Verify TenantAwareTask binds tenant_id before start and cleans up after return."""
    reset_tenant_context()
    assert get_current_tenant_id() == DEFAULT_TENANT_ID

    recorded_tenant_inside = []

    class DummyTask(TenantAwareTask):
        name = "test.dummy_task"
        def run(self, *args, **kwargs):
            recorded_tenant_inside.append(get_current_tenant_id())
            return "ok"

    dummy = DummyTask()

    # Simulate Celery worker execution cycle
    dummy.before_start("task_123", (), {"tenant_id": "tenant_enterprise_beta"})
    res = dummy.run(tenant_id="tenant_enterprise_beta")
    dummy.after_return("SUCCESS", res, "task_123", (), {"tenant_id": "tenant_enterprise_beta"}, None)

    assert recorded_tenant_inside == ["tenant_enterprise_beta"]
    # Context must be cleanly reset
    assert get_current_tenant_id() == DEFAULT_TENANT_ID


def test_cryptographic_and_perceptual_deduplication():
    """Verify SHA256 checksums and perceptual difference hash (dHash) matching."""
    img1 = make_test_image(120, 120, pattern="gradient")
    img2 = make_test_image(120, 120, pattern="gradient")  # Identical
    img3 = make_test_image(96, 96, pattern="gradient")     # Resized duplicate
    diff_img = make_test_image(120, 120, pattern="stripes")  # Totally different pattern

    # 1. SHA256
    sha1 = compute_sha256(img1)
    sha2 = compute_sha256(img2)
    sha_diff = compute_sha256(diff_img)
    assert sha1 == sha2
    assert sha1 != sha_diff

    # 2. pHash (dHash)
    ph1 = compute_phash(img1)
    ph2 = compute_phash(img2)
    ph3 = compute_phash(img3)
    ph_diff = compute_phash(diff_img)

    assert ph1 == ph2
    # Resized version should have low Hamming distance
    dist_resized = hamming_distance(ph1, ph3)
    assert dist_resized <= 3
    assert is_perceptual_duplicate(ph1, ph3) is True

    # Totally different pattern should have large Hamming distance
    assert hamming_distance(ph1, ph_diff) > 3


def test_task_process_image_upload_duplicate_skipping():
    """Verify that submitting an existing duplicate image skips deep inference."""
    img_bytes = make_test_image(100, 100, color=(150, 150, 150))
    sha256 = compute_sha256(img_bytes)
    phash = compute_phash(img_bytes)

    fake_duplicate = {
        "int_id": 999,
        "vector_id": "face_existing_1",
        "url": "https://s3.amazonaws.com/bucket/existing.jpg",
        "folder": "wedding",
    }

    with patch("src.tasks.ingest_tasks.find_duplicate_image", return_value=fake_duplicate):
        res = task_process_image_upload(
            file_bytes_or_path=img_bytes,
            folder_name="wedding",
            tenant_id="tenant_alpha",
            image_id="img_new_upload",
            job_id="job_test_1",
        )
        assert res["status"] == "duplicate_skipped"
        assert res["existing_vector_id"] == "face_existing_1"

        # Pass piped output to inference task (chain simulation)
        infer_res = task_extract_embeddings(res)
        # Should short-circuit without executing inference
        assert infer_res["status"] == "duplicate_skipped"


def test_durable_s3_reference_cross_pod_execution():
    """Verify inference task loads image via durable S3 object reference without shared local disk."""
    test_bytes = make_test_image(100, 100, pattern="gradient")

    ingest_payload = {
        "image_id": "img_crosspod_1",
        "folder_name": "vacation",
        "s3_key": "tenant_pod_x/vacation/img_crosspod_1.jpg",
        "local_path": "/nonexistent/pod_a/path.jpg",  # Simulates missing path on Pod B!
        "cloud_url": "https://bucket.s3.amazonaws.com/tenant_pod_x/vacation/img_crosspod_1.jpg",
        "status": "ingested",
        "tenant_id": "tenant_pod_x",
        "user_id": "user_pod",
        "job_id": "job_crosspod_1",
    }

    with patch("src.tasks.inference_tasks.download_image_from_s3", return_value=test_bytes) as mock_s3_get:
        infer_res = task_extract_embeddings(ingest_payload)
        # Verify durable S3 download was called because local path didn't exist
        mock_s3_get.assert_called_once_with("tenant_pod_x/vacation/img_crosspod_1.jpg")
        assert "faces_detected" in infer_res or infer_res.get("status") == "success"


def test_atomic_multi_counter_telemetry():
    """Verify record_task_outcome updates processed, successful, duplicate, and failed counts."""
    from src.modules.infra.kv_cache import get_kv_cache
    import uuid
    cache = get_kv_cache()
    jid = f"job_telemetry_test_{uuid.uuid4().hex[:8]}"
    tid = "tenant_telem"

    # 1. Record successful
    record_task_outcome(job_id=jid, tenant_id=tid, outcome="successful", log_msg="Image 1 ok")
    # 2. Record duplicate
    record_task_outcome(job_id=jid, tenant_id=tid, outcome="duplicate", log_msg="Image 2 dup")
    # 3. Record failed
    record_task_outcome(job_id=jid, tenant_id=tid, outcome="failed", log_msg="Image 3 corrupt")

    cached = cache.get(f"job:{tid}:{jid}")
    assert cached is not None
    assert cached["processed_files"] == 3
    assert cached["successful_files"] == 1
    assert cached["duplicate_files"] == 1
    assert cached["failed_files"] == 1
    assert len(cached["logs"]) == 3


def test_outcome_aware_batch_completion_statuses():
    """Verify batch callback evaluates real business outcomes: completed, completed_with_errors, failed."""
    from src.modules.infra.kv_cache import get_kv_cache
    cache = get_kv_cache()

    # Case 1: 100% Successful
    cache.set("job:t1:job_all_good", {
        "total_files": 3,
        "processed_files": 3,
        "successful_files": 2,
        "duplicate_files": 1,
        "failed_files": 0,
    })
    with patch("src.tasks.clustering_tasks.task_run_face_clustering.apply_async") as mock_cluster:
        res1 = task_batch_completion_callback([], job_id="job_all_good", tenant_id="t1", folder_name="f1")
        assert res1["status"] == "completed"
        mock_cluster.assert_called_once()

    # Case 2: Partial failure (completed_with_errors)
    cache.set("job:t1:job_partial", {
        "total_files": 3,
        "processed_files": 3,
        "successful_files": 1,
        "duplicate_files": 1,
        "failed_files": 1,
    })
    with patch("src.tasks.clustering_tasks.task_run_face_clustering.apply_async") as mock_cluster2:
        res2 = task_batch_completion_callback([], job_id="job_partial", tenant_id="t1", folder_name="f1")
        assert res2["status"] == "completed_with_errors"
        mock_cluster2.assert_called_once()

    # Case 3: Complete failure (failed) - clustering MUST NOT trigger
    cache.set("job:t1:job_failed", {
        "total_files": 3,
        "processed_files": 3,
        "successful_files": 0,
        "duplicate_files": 0,
        "failed_files": 3,
    })
    with patch("src.tasks.clustering_tasks.task_run_face_clustering.apply_async") as mock_cluster3:
        res3 = task_batch_completion_callback([], job_id="job_failed", tenant_id="t1", folder_name="f1")
        assert res3["status"] == "failed"
        mock_cluster3.assert_not_called()
