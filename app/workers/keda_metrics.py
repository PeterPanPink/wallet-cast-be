"""KEDA metrics collection for Streaq workers.

This module provides functionality to publish worker metrics to Redis
for Kubernetes KEDA (Event-driven Autoscaling) to consume.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from streaq import Worker


KEDA_METRICS_PREFIX = "wallet-cast-demo:keda:metrics"
KEDA_METRICS_TTL_SECONDS = 60


@dataclass(frozen=True, slots=True)
class WorkerMetrics:
    """Snapshot of worker metrics for KEDA scaling decisions."""

    worker_id: str
    queue_name: str
    concurrency: int
    active_tasks: int
    idle_slots: int
    queue_size: int
    completed: int = 0
    failed: int = 0
    retried: int = 0
    timestamp: float = field(default_factory=time.time)


def _build_worker_metrics_key(queue_name: str, worker_id: str) -> str:
    """Build Redis key for individual worker metrics."""
    return f"{KEDA_METRICS_PREFIX}:{queue_name}:worker:{worker_id}"


def _build_queue_metrics_key(queue_name: str) -> str:
    """Build Redis key for aggregated queue metrics."""
    return f"{KEDA_METRICS_PREFIX}:{queue_name}:queue"


async def collect_worker_metrics(worker: Worker, queue_size: int | None = None) -> WorkerMetrics:
    """Collect current metrics from a Streaq worker."""
    if queue_size is None:
        queue_size = await worker.queue_size()

    counters = worker.counters
    active = worker.active

    return WorkerMetrics(
        worker_id=worker.id,
        queue_name=worker.queue_name,
        concurrency=worker.concurrency,
        active_tasks=active,
        idle_slots=max(0, worker.concurrency - active),
        queue_size=queue_size,
        completed=counters.get("completed", 0),
        failed=counters.get("failed", 0),
        retried=counters.get("retried", 0),
    )


async def publish_worker_metrics(
    redis: Any,
    metrics: WorkerMetrics,
    ttl: int = KEDA_METRICS_TTL_SECONDS,
) -> None:
    """Publish worker metrics to Redis for KEDA consumption."""
    worker_key = _build_worker_metrics_key(metrics.queue_name, metrics.worker_id)
    queue_key = _build_queue_metrics_key(metrics.queue_name)

    worker_data: dict[str, str] = {
        "worker_id": metrics.worker_id,
        "concurrency": str(metrics.concurrency),
        "active_tasks": str(metrics.active_tasks),
        "idle_slots": str(metrics.idle_slots),
        "completed": str(metrics.completed),
        "failed": str(metrics.failed),
        "retried": str(metrics.retried),
        "timestamp": str(metrics.timestamp),
    }

    queue_data: dict[str, str] = {
        "queue_size": str(metrics.queue_size),
        "timestamp": str(metrics.timestamp),
    }

    pipe = await redis.pipeline(transaction=False)
    pipe.hset(worker_key, mapping=worker_data)  # type: ignore[arg-type]
    pipe.expire(worker_key, ttl)
    pipe.hset(queue_key, mapping=queue_data)  # type: ignore[arg-type]
    pipe.expire(queue_key, ttl)
    await pipe.execute()

    logger.debug(
        "Published KEDA metrics: queue={} worker={} idle={} active={} queued={}",
        metrics.queue_name,
        metrics.worker_id,
        metrics.idle_slots,
        metrics.active_tasks,
        metrics.queue_size,
    )


async def collect_and_publish_metrics(
    worker: Worker,
    redis: Any = None,
    ttl: int = KEDA_METRICS_TTL_SECONDS,
) -> WorkerMetrics:
    """Collect and publish worker metrics in one call."""
    if redis is None:
        redis = worker.redis

    metrics = await collect_worker_metrics(worker)
    await publish_worker_metrics(redis, metrics, ttl)
    return metrics
