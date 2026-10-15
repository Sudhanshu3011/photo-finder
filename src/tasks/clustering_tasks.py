"""
src/tasks/clustering_tasks.py — Distributed Clustering Tasks (queue.clustering).
Runs HDBSCAN face clustering, selects identity medoids, and updates PostgreSQL face clusters.
"""
from typing import Any, Dict, Optional

from celery_app import app
from src.core.logging import log
from src.core.tenant_context import DEFAULT_TENANT_ID, set_current_tenant_id
from src.modules.infra.kv_cache import get_kv_cache
from src.services.image_processing_service import ImageProcessingService
from src.tasks.base import TenantAwareTask


@app.task(
    bind=True,
    base=TenantAwareTask,
    name="src.tasks.clustering_tasks.task_run_face_clustering",
    max_retries=2,
    default_retry_delay=15,
)
def task_run_face_clustering(
    self,
    folder_name: Optional[str] = None,
    min_cluster_size: int = 3,
    epsilon: float = 0.25,
    tenant_id: str = DEFAULT_TENANT_ID,
    user_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Dedicated clustering task running on queue.clustering pool.
    Groups tenant face embeddings into named albums and writes cluster metadata.
    """
    set_current_tenant_id(tenant_id)
    log("INFO", "tasks.clustering.start", folder=folder_name, tenant_id=tenant_id)

    try:
        svc = ImageProcessingService()
        result = svc.trigger_face_clustering(
            min_cluster_size=min_cluster_size,
            epsilon=epsilon,
            folder_name=folder_name,
            user_id=user_id,
            tenant_id=tenant_id,
        )

        if job_id:
            cache = get_kv_cache()
            key = f"job:{tenant_id}:{job_id}"
            cached = cache.get(key) or cache.get(f"job:{job_id}")
            if isinstance(cached, dict):
                logs = cached.get("logs", [])
                logs.append(f"Identity clustering completed: {result.get('clusters_found', 0)} clusters created.")
                cached["logs"] = logs
                cache.set(key, cached)
                cache.set(f"job:{job_id}", cached)

        log("INFO", "tasks.clustering.success", clusters=result.get("clusters_found", 0), tenant_id=tenant_id)
        return result

    except Exception as exc:
        log("ERROR", "tasks.clustering.error", folder=folder_name, tenant_id=tenant_id, error=str(exc))
        if self.request.retries < self.max_retries:
            raise self.retry(exc=exc)
        return {
            "status": "failed",
            "folder": folder_name,
            "error": str(exc),
            "tenant_id": tenant_id,
        }

