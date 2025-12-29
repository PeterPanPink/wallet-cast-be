"""Egress cleanup operations for session end-of-life handling.

This module handles the delayed cleanup after a live stream ends.
When a stream transitions to ENDING state, we wait for Mux to confirm
the stream is no longer active before transitioning to STOPPED.
"""

from __future__ import annotations

import asyncio

from loguru import logger

from app.app_config import get_app_environ_config
from app.schemas import Session, SessionState
from app.services.integrations.external_live.external_live_client import ExternalLiveClient
from app.services.integrations.external_live.external_live_schemas import AdminStopLiveBody
from app.services.integrations.mux_service import mux_service

# Default delay before checking Mux stream status (in seconds)
DEFAULT_CLEANUP_DELAY_SECONDS = 60


def _get_external_live_client() -> ExternalLiveClient | None:
    """Get External Live client if configured."""
    config = get_app_environ_config()
    if not config.EXTERNAL_LIVE_BASE_URL:
        logger.debug("EXTERNAL_LIVE_BASE_URL not configured, skipping External Live integration")
        return None
    logger.debug(f"Initializing External Live client: base_url={config.EXTERNAL_LIVE_BASE_URL}")
    return ExternalLiveClient(
        base_url=config.EXTERNAL_LIVE_BASE_URL,
        api_key=config.EXTERNAL_LIVE_API_KEY,
    )


async def _call_external_live_stop_live(session: Session) -> bool:
    """Call External Live admin/live/stop endpoint.

    Args:
        session: Session document with external_live_post_id in config

    Returns:
        True if successful, False otherwise
    """
    client = _get_external_live_client()
    if not client:
        return False

    try:
        # Get post_id from session config
        config = session.runtime
        post_id = config.post_id

        logger.debug(
            f"Attempting External Live stop_live: session_id={session.session_id}, "
            f"user_id={session.user_id}, post_id={post_id}"
        )

        if not post_id:
            logger.warning(f"No external_live_post_id in session {session.session_id}, skipping stop_live")
            return False

        body = AdminStopLiveBody(
            user_id=session.user_id,
            post_id=post_id,
        )

        logger.info(
            f"📤 Calling External Live admin/live/stop for session {session.session_id}, post_id={post_id}"
        )
        logger.debug(f"External Live stop_live request body: {body.model_dump_json(indent=2)}")
        await client.admin_stop_live(body)
        logger.info(f"✅ External Live stop_live completed for post_id: {post_id}")
        return True

    except Exception as e:
        logger.exception(f"Failed to call External Live admin/live/stop: {e}")
        return False


async def _transition_session_to_stopped(session: Session) -> Session | None:
    """Transition a session from ENDING to STOPPED state.

    Args:
        session: Session document to transition

    Returns:
        Updated session if successful, None otherwise
    """
    from .session_state_machine import SessionStateMachine

    if session.status != SessionState.ENDING:
        logger.warning(
            f"Session {session.session_id} is not in ENDING state "
            f"(current: {session.status}), skipping transition"
        )
        return None

    if not SessionStateMachine.can_transition(session.status, SessionState.STOPPED):
        logger.error(
            f"Invalid state transition from {session.status} to STOPPED for "
            f"session {session.session_id}"
        )
        return None

    from ._base import BaseService

    base_service = BaseService()
    updated_session = await base_service.update_session_state(session, SessionState.STOPPED)
    logger.info(f"✅ Session {session.session_id} transitioned ENDING -> STOPPED")
    return updated_session


async def delayed_stream_cleanup(
    session_id: str,
    mux_stream_id: str,
    delay_seconds: int = DEFAULT_CLEANUP_DELAY_SECONDS,
) -> None:
    """Delayed cleanup task for checking Mux stream status and finalizing session.

    This task:
    1. Waits for the specified delay
    2. Checks if the Mux live stream is still active
    3. If not active, transitions the session to STOPPED and notifies External Live
    4. Recreates a new READY session for the same room_id

    Args:
        session_id: Session ID to process
        mux_stream_id: Mux stream ID to check status for
        delay_seconds: Delay in seconds before checking (default: 60)
    """
    logger.info(
        f"⏱️  Starting delayed cleanup for session {session_id}, "
        f"mux_stream_id={mux_stream_id}, delay={delay_seconds}s"
    )

    try:
        # Step 1: Wait for the specified delay
        await asyncio.sleep(delay_seconds)
        logger.info(f"⏱️  Delay complete for session {session_id}, checking Mux stream status")

        # Step 2: Fetch current session state from database
        session = await Session.find_one(Session.session_id == session_id)
        if not session:
            logger.warning(f"Session {session_id} not found, cleanup cancelled")
            return

        # Only proceed if session is still in ENDING state
        if session.status != SessionState.ENDING:
            logger.info(
                f"Session {session_id} is no longer in ENDING state "
                f"(current: {session.status}), cleanup not needed"
            )
            return

        # Step 3: Check Mux stream status
        try:
            mux_stream = mux_service.get_live_stream(mux_stream_id)
            stream_status = mux_stream.data.status
            logger.info(
                f"Mux stream {mux_stream_id} status: {stream_status} (session {session_id})"
            )

            # Only proceed if stream is not active
            if stream_status == "active":
                logger.info(
                    f"Mux stream {mux_stream_id} is still active, "
                    f"will not transition session {session_id} to STOPPED yet"
                )
                return

        except Exception as e:
            # If we can't get stream status, log warning and proceed with cleanup
            # (stream may have been deleted or there's an API issue)
            logger.warning(
                f"Failed to get Mux stream status for {mux_stream_id}: {e}. "
                f"Proceeding with cleanup for session {session_id}"
            )

        # Step 4: Call External Live admin/live/stop before transitioning
        external_live_stopped = await _call_external_live_stop_live(session)
        logger.debug(f"External Live stop_live result for session {session_id}: {external_live_stopped}")

        # Step 5: Transition session to STOPPED
        updated_session = await _transition_session_to_stopped(session)
        if not updated_session:
            logger.error(f"Failed to transition session {session_id} to STOPPED")
            return

        logger.info(f"✅ Delayed cleanup completed for session {session_id}")

    except Exception as e:
        logger.error(
            f"Error in delayed cleanup for session {session_id}: {e}",
            exc_info=True,
        )


def schedule_delayed_cleanup(
    session_id: str,
    mux_stream_id: str,
    delay_seconds: int = DEFAULT_CLEANUP_DELAY_SECONDS,
) -> asyncio.Task:
    """Schedule a delayed cleanup task for a session.

    Creates an asyncio task that will run the delayed cleanup after the
    specified delay. The task runs independently and does not block.

    Args:
        session_id: Session ID to process
        mux_stream_id: Mux stream ID to check status for
        delay_seconds: Delay in seconds before checking (default: 60)

    Returns:
        The created asyncio.Task for the cleanup operation
    """
    task = asyncio.create_task(
        delayed_stream_cleanup(
            session_id=session_id,
            mux_stream_id=mux_stream_id,
            delay_seconds=delay_seconds,
        ),
        name=f"cleanup-{session_id}",
    )
    logger.info(
        f"📅 Scheduled delayed cleanup task for session {session_id} (delay={delay_seconds}s)"
    )
    return task
