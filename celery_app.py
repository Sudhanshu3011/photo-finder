"""
celery_app.py — Production Celery Application Instance & Distributed Worker Fleet Configuration.
Segregates tasks across dedicated priority queues: queue.ingest, queue.inference, and queue.clustering.
Guarantees tenant context isolation, message durability, and late acknowledgements.
"""
import os
from celery import Celery
from src.core.config import (
    CELERY_BROKER_URL,
    CELERY_RESULT_BACKEND,
    CELERY_TASK_ALWAYS_EAGER,
)

# 1. Instantiate Celery Fleet Application
app = Celery(
    "visual_search_fleet",
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=[
        "src.tasks.ingest_tasks",
        "src.tasks.inference_tasks",
        "src.tasks.clustering_tasks",
    ],
)

# 2. Celery Production Configuration
app.conf.update(
    # Serialization & Security
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,

    # Reliability & Worker Failure Resilience
    task_acks_late=True,                 # Re-queue task if worker dies mid-flight
    task_reject_on_worker_lost=True,     # Guard against OOM or killed worker processes
    task_track_started=True,             # Track when task switches from PENDING to STARTED
    task_time_limit=600,                 # Hard timeout: 10 minutes max per task
    task_soft_time_limit=540,            # Soft timeout: 9 minutes to raise SoftTimeLimitExceeded

    # Offline / Test Eager Mode
    task_always_eager=CELERY_TASK_ALWAYS_EAGER,
    task_eager_propagates=True,

    # Task Priority Queue Routing Topology
    task_routes={
        "src.tasks.ingest_tasks.*": {"queue": "queue.ingest"},
        "src.tasks.inference_tasks.*": {"queue": "queue.inference"},
        "src.tasks.clustering_tasks.*": {"queue": "queue.clustering"},
    },

    # Redis Broker Transport Options (TTL, visibility, socket timeouts)
    broker_transport_options={
        "visibility_timeout": 43200,     # 12 hours visibility timeout
        "socket_timeout": 15,
        "socket_connect_timeout": 15,
        "retry_on_timeout": True,
    },
    result_expires=86400,                # 24 hour TTL for task results in Redis
)

if __name__ == "__main__":
    app.start()

