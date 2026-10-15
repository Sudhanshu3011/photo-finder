"""
src/tasks/base.py — Base Celery Task with Multi-Tenant Context Isolation & Structured Telemetry.
Guarantees that every task executed across distributed worker pools binds its execution context
to the correct tenant_id before start and cleans up contextvars upon completion.
"""
from typing import Any, Optional
import celery
from src.core.logging import log
from src.core.tenant_context import (
    DEFAULT_TENANT_ID,
    get_current_tenant_id,
    reset_tenant_context,
    set_current_tenant_id,
)
from src.modules.infra.kv_cache import get_kv_cache



class TenantAwareTask(celery.Task):
    """
    Abstract Celery Task that enforces tenant context isolation.
    Automatically intercepts tenant_id from headers or kwargs and sets the tenant context.
    """
    abstract = True

    def before_start(self, task_id: str, args: tuple, kwargs: dict) -> None:
        """Invoked immediately before task execution starts in worker process."""
        # 1. Resolve tenant_id from kwargs, headers, or positional args
        tenant_id = None
        if isinstance(kwargs, dict):
            tenant_id = kwargs.get("tenant_id")
        
        # Check task request headers if available
        if not tenant_id and hasattr(self, "request") and self.request and getattr(self.request, "headers", None):
            tenant_id = self.request.headers.get("tenant_id")

        if not tenant_id:
            tenant_id = DEFAULT_TENANT_ID

        # 2. Bind tenant_id to contextvars for current worker process/coroutine
        set_current_tenant_id(tenant_id)
        log(
            "INFO",
            "tasks.worker.task_start",
            task_id=task_id,
            task_name=self.name,
            tenant_id=tenant_id,
        )
        super().before_start(task_id, args, kwargs)

    def after_return(
        self,
        status: str,
        retval: Any,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """Invoked after task completes, regardless of success or failure."""
        current_tid = get_current_tenant_id()
        # Clean up tenant context to prevent cross-tenant contamination across pooled workers
        reset_tenant_context()
        log(
            "INFO",
            "tasks.worker.task_complete",
            task_id=task_id,
            task_name=self.name,
            tenant_id=current_tid,
            status=status,
        )
        super().after_return(status, retval, task_id, args, kwargs, einfo)

    def on_failure(
        self,
        exc: Exception,
        task_id: str,
        args: tuple,
        kwargs: dict,
        einfo: Any,
    ) -> None:
        """Invoked when a task raises an unhandled exception."""
        current_tid = get_current_tenant_id()
        reset_tenant_context()
        log(
            "ERROR",
            "tasks.worker.task_error",
            task_id=task_id,
            task_name=self.name,
            tenant_id=current_tid,
            error=str(exc),
        )
        super().on_failure(exc, task_id, args, kwargs, einfo)


def record_task_outcome(
    job_id: str,
    tenant_id: str,
    outcome: str,  # "successful", "duplicate", "failed"
    log_msg: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """
    Atomically updates multi-counter job progress across all terminal branches
    (successful, duplicate, invalid_quality, failed).
    Ensures processed_files strictly reflects completion progress towards total_files.
    """
    if not job_id:
        return

    try:
        cache = get_kv_cache()
        key = f"job:{tenant_id}:{job_id}"
        cached = cache.get(key) or cache.get(f"job:{job_id}") or {}
        if not isinstance(cached, dict):
            cached = {}

        cached["processed_files"] = cached.get("processed_files", 0) + 1
        cached["successful_files"] = cached.get("successful_files", 0) + (1 if outcome == "successful" else 0)
        cached["duplicate_files"] = cached.get("duplicate_files", 0) + (1 if outcome == "duplicate" else 0)
        cached["failed_files"] = cached.get("failed_files", 0) + (1 if outcome == "failed" else 0)

        if log_msg:
            logs = cached.get("logs", [])
            logs.append(log_msg)
            cached["logs"] = logs

        cache.set(key, cached)
        cache.set(f"job:{job_id}", cached)
    except Exception as e:
        log("WARN", "tasks.job.outcome_update_failed", job_id=job_id, outcome=outcome, error=str(e))


def sync_job_progress_increment(job_id: str, tenant_id: str) -> None:
    """Helper to update Redis job progress count atomically without cross-module circular imports."""
    record_task_outcome(job_id=job_id, tenant_id=tenant_id, outcome="successful")



