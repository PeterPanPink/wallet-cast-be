"""Streaq worker for API maintenance jobs."""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from loguru import logger
from streaq import Worker

from app.shared.api.utils import init_logger
from app.shared.storage.redis import get_redis_client
from app.domain.livekit_agents.caption_agent.service import initialize_beanie_for_worker
from app.workers.base import QUEUE_KEY, queue_url, redis_major_label
from app.workers.keda_metrics import collect_and_publish_metrics

QUEUE_KEY_API_JOBS = f"{QUEUE_KEY}:api-jobs"

# Time to wait before cleaning up session after host leaves (10 minutes)
HOST_CLEANUP_DELAY = timedelta(minutes=10)


@asynccontextmanager
async def api_jobs_lifespan() -> AsyncIterator[None]:
    """Lifespan context manager for API jobs worker."""
    init_logger()
    logger.info("Starting API jobs worker")
    await initialize_beanie_for_worker()
    logger.info("API jobs worker initialized")

    try:
        yield
    finally:
        logger.info("API jobs worker stopped")


worker: Worker[None] = Worker(
    redis_url=queue_url,
    lifespan=api_jobs_lifespan,  # type: ignore[arg-type]
    queue_name=QUEUE_KEY_API_JOBS,
)


@worker.task(ttl=timedelta(hours=1))
async def cleanup_session_after_host_left(session_id: str) -> dict[str, Any]:
    """Cleanup session after host has been absent for the configured delay.

    This task is scheduled when the host leaves the room and will:
    1. Verify the host is still absent (check if cleanup task ID matches)
    2. Stop egress and signal Mux stream complete (if active)
    3. Delete the LiveKit room
    4. Update session state to ABORTED -> STOPPED

    Args:
        session_id: The session ID to clean up

    Returns:
        Dict with cleanup result information
    """
    from app.domain.live.session.session_domain import SessionService
    from app.schemas import Session, SessionState
    from app.services.integrations.livekit_service import livekit_service
    from app.services.integrations.mux_service import mux_service
    from app.utils.app_errors import AppError, AppErrorCode

    logger.info(f"🧹 Running cleanup for session {session_id} after host left")

    try:
        session = await Session.find_one(Session.session_id == session_id)
        if not session:
            logger.warning(f"Session {session_id} not found, skipping cleanup")
            return {"status": "skipped", "reason": "session_not_found"}

        # Check if session is already in a terminal state
        if session.status in (SessionState.STOPPED, SessionState.CANCELLED):
            logger.info(f"Session {session_id} already in terminal state {session.status}")
            return {"status": "skipped", "reason": "already_terminal"}

        # Check if the cleanup task ID matches (host hasn't returned and cancelled the task)
        current_task_id = worker.task_context().task_id
        if (
            session.runtime.host_cleanup is None
            or session.runtime.host_cleanup.task_id != current_task_id
        ):
            logger.info(
                f"Cleanup task ID mismatch for session {session_id}, host may have returned"
            )
            return {"status": "skipped", "reason": "task_id_mismatch"}

        service = SessionService()

        # Get egress and Mux info for cleanup
        egress_id = session.runtime.livekit.egress_id if session.runtime.livekit else None
        mux_stream_id = session.runtime.mux.mux_stream_id if session.runtime.mux else None

        # Stop egress if active (following end_live pattern)
        if egress_id:
            try:
                logger.info(f"Stopping LiveKit egress: egress_id={egress_id}")
                await livekit_service.stop_egress(egress_id)
                logger.info(f"✅ Stopped LiveKit egress: {egress_id}")
            except Exception as e:
                error_str = str(e)
                if (
                    "EGRESS_COMPLETE" in error_str
                    or "EGRESS_ENDING" in error_str
                    or "EGRESS_LIMIT_REACHED" in error_str
                ):
                    logger.info(f"LiveKit egress {egress_id} already completed/ending: {error_str}")
                else:
                    logger.warning(f"Failed to stop egress {egress_id}: {error_str}")

        # Signal Mux stream complete if active
        if mux_stream_id:
            try:
                logger.info(f"Signaling Mux stream complete: {mux_stream_id}")
                mux_service.signal_live_stream_complete(mux_stream_id)
                logger.info(f"✅ Signaled Mux stream complete: {mux_stream_id}")
            except Exception as e:
                logger.warning(f"Failed to signal Mux stream complete {mux_stream_id}: {e}")

        # Delete the LiveKit room
        try:
            await service.delete_room(room_name=session.room_id)
            logger.info(f"✅ Deleted LiveKit room {session.room_id}")
        except AppError as e:
            if e.errcode == AppErrorCode.E_SESSION_NOT_FOUND:
                logger.warning(f"Room {session.room_id} already deleted")
            else:
                raise

        # Transition session state: current -> ABORTED -> STOPPED
        with contextlib.suppress(AppError):
            await service.update_session_state(
                session_id=session_id,
                new_state=SessionState.ABORTED,
            )

        await service.update_session_state(
            session_id=session_id,
            new_state=SessionState.STOPPED,
        )

        # Clear the cleanup runtime data atomically
        # Refresh session after state updates
        session = await Session.find_one(Session.session_id == session_id)
        if session:
            session.runtime.host_cleanup = None
            await session.partial_update_session_with_version_check(
                {Session.runtime: session.runtime},
                max_retry_on_conflicts=2,
            )

        logger.info(f"✅ Session {session_id} cleaned up after host absence: ABORTED -> STOPPED")
        return {"status": "completed", "session_id": session_id}

    except Exception as e:
        logger.exception(f"Failed to cleanup session {session_id}: {e}")
        raise


@worker.cron("*/15 * * * * * *")
async def publish_keda_metrics() -> None:
    """Publish worker metrics to Redis for KEDA autoscaling."""
    redis = get_redis_client(redis_major_label)
    await collect_and_publish_metrics(worker, redis=redis)
