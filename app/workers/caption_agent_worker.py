"""Streaq worker for caption agent management.

This worker handles tasks for starting/stopping caption agents
and runs the LiveKit agent server in the background.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from loguru import logger
from streaq import Worker

from app.shared.api.utils import init_logger
from app.shared.storage.redis import get_redis_client, get_redis_manager
from app.shared.worker import WorkerData
from app.domain.livekit_agents.caption_agent import (
    CaptionAgentParams,
    CaptionAgentService,
    initialize_beanie_for_worker,
)
from app.workers.base import QUEUE_KEY, queue_url, redis_major_label
from app.workers.keda_metrics import collect_and_publish_metrics

QUEUE_KEY_CAPTION_AGENT = f"{QUEUE_KEY}:caption-agent"

# Feature flag for S3 uploads
S3_ENABLED = False


@dataclass
class CaptionWorkerContext:
    """Context for caption agent worker tasks."""

    worker_data: WorkerData
    caption_service: CaptionAgentService


@asynccontextmanager
async def caption_lifespan() -> AsyncIterator[CaptionWorkerContext]:
    """Lifespan context manager for caption agent worker."""
    init_logger()
    logger.info("Starting caption agent worker")

    await initialize_beanie_for_worker()

    worker_data = WorkerData()
    await worker_data.initialize()

    caption_service = CaptionAgentService(redis_label=redis_major_label)
    await caption_service.start_agent_server()

    if S3_ENABLED:
        caption_service.start_s3_uploader()
    else:
        logger.info("S3 caption upload is disabled")

    context = CaptionWorkerContext(worker_data=worker_data, caption_service=caption_service)
    logger.info("Caption agent worker initialized")

    try:
        yield context
    finally:
        logger.info("Stopping background tasks...")
        await caption_service.stop_s3_uploader()
        await caption_service.stop_agent_server()
        await worker_data.clean()
        await get_redis_manager().close_all()
        logger.info("All background tasks stopped")


worker: Worker[CaptionWorkerContext] = Worker(
    redis_url=queue_url,
    lifespan=caption_lifespan,  # type: ignore[arg-type]
    queue_name=QUEUE_KEY_CAPTION_AGENT,
)


@worker.task()
async def start_caption_agent(params: dict | CaptionAgentParams) -> dict[str, Any]:
    """Task to start a caption agent for a session."""
    if isinstance(params, dict):
        params = CaptionAgentParams(**params)
    ctx = worker.context
    return await ctx.caption_service.start_caption_agent(params)


@worker.task()
async def stop_caption_agent(session_id: str) -> dict[str, Any]:
    """Task to stop a caption agent for a session."""
    ctx = worker.context
    return await ctx.caption_service.stop_caption_agent(session_id)


@worker.cron("*/15 * * * * * *")
async def publish_keda_metrics() -> None:
    """Publish worker metrics to Redis for KEDA autoscaling."""
    redis = get_redis_client(redis_major_label)
    await collect_and_publish_metrics(worker, redis=redis)
