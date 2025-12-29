"""Egress startup operations for session initialization.

This module handles the delayed check after a live stream starts publishing.
When a stream transitions to PUBLISHING state, we periodically check if Mux
reports the stream as active, then transition to LIVE and notify External Live.
"""

from __future__ import annotations

import asyncio
import uuid

from loguru import logger

from app.app_config import get_app_environ_config
from app.schemas import Channel, Session, SessionState
from app.services.integrations.external_live.external_live_client import ExternalLiveClient
from app.services.integrations.external_live.external_live_schemas import (
    AdminStartLiveBody,
    ExternalLiveApiSuccess,
    ChannelConfig,
    SessionConfig,
)
from app.services.integrations.mux_service import mux_service
from app.utils.app_errors import AppError, AppErrorCode

# Default delay before first check (in seconds)
DEFAULT_STARTUP_DELAY_SECONDS = 30

# Maximum number of retries to check for active stream
MAX_RETRIES = 10

# Delay between retry checks (in seconds)
RETRY_DELAY_SECONDS = 30


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


async def _call_external_live_start_live(
    session: Session,
    channel: Channel,
) -> str | None:
    """Call External Live admin/live/start endpoint.

    Args:
        session: Session document with config containing Mux info
        channel: Channel document for channel metadata

    Returns:
        post_id from response if successful, None otherwise
    """
    client = _get_external_live_client()
    if not client:
        # Generate mock post_id when external-live is not available
        mock_post_id = f"mock_{uuid.uuid4().hex[:16]}"
        logger.info(f"🔧 External Live not configured, using mock post_id: {mock_post_id}")
        return mock_post_id

    # Check if post_id already exists
    if session.runtime.post_id:
        logger.info(
            f"⏭️  External Live start_live already called for session {session.session_id}, "
            f"post_id={session.runtime.post_id}, skipping"
        )
        return session.runtime.post_id

    try:
        # Extract config data
        config = session.runtime
        mux_stream_id = (config.mux.mux_stream_id if config.mux else None) or ""
        mux_rtmp_url = (config.mux.mux_rtmp_url if config.mux else None) or ""
        mux_stream_key = (config.mux.mux_stream_key if config.mux else None) or ""
        live_playback_url = config.live_playback_url or ""
        animated_url = config.animated_url or ""
        thumbnail_url = config.thumbnail_url or ""
        storyboard_url = config.storyboard_url or ""

        # Build full RTMP ingest URL with stream key
        # Format: rtmps://global-live.mux.com:443/app/{stream_key}
        mux_rtmp_ingest_url = (
            f"{mux_rtmp_url}/{mux_stream_key}" if mux_rtmp_url and mux_stream_key else ""
        )

        logger.debug(
            f"Extracted session config for External Live start_live: "
            f"session_id={session.session_id}, user_id={session.user_id}, "
            f"channel_id={session.channel_id}, mux_stream_id={mux_stream_id}, "
            f"mux_rtmp_ingest_url={mux_rtmp_ingest_url}, live_playback_url={live_playback_url}"
        )

        body = AdminStartLiveBody(
            user_id=session.user_id,
            channel=ChannelConfig(
                channelId=channel.channel_id,
                dsc=channel.description,
                img=channel.cover or "",
                lang=channel.lang or "en",
                ttl=channel.title or "",
                categoryIds=channel.category_ids or [],
                location=channel.location or "",
            ),
            session=SessionConfig(
                sid=session.session_id,
                url=live_playback_url,
                animatedUrl=animated_url,
                thumbnailUrl=thumbnail_url,
                thumbnails=storyboard_url,
                mux_stream_id=mux_stream_id,
                mux_rtmp_ingest_url=mux_rtmp_ingest_url,
            ),
        )

        logger.info(f"📤 Calling External Live admin/live/start for session {session.session_id}")
        logger.debug(f"External Live start_live request body: {body.model_dump_json(indent=2)}")
        response = await client.admin_start_live(body)

        if not isinstance(response.root, ExternalLiveApiSuccess):
            raise AppError(
                errcode=AppErrorCode.E_EXTERNAL_LIVE_ERROR,
                errmesg=f"External Live admin/live/start failed: {response.root.errmesg}",
            )

        post_id = response.root.results.post_id
        logger.info(f"✅ External Live start_live returned post_id: {post_id}")
        return post_id

    except Exception as e:
        logger.exception(f"Failed to call External Live admin/live/start: {e}")
        raise


async def _transition_session_to_live(session: Session) -> Session | None:
    """Transition a session from PUBLISHING to LIVE state.

    Args:
        session: Session document to transition

    Returns:
        Updated session if successful, None otherwise
    """
    from .session_state_machine import SessionStateMachine

    if session.status != SessionState.PUBLISHING:
        logger.warning(
            f"Session {session.session_id} is not in PUBLISHING state "
            f"(current: {session.status}), skipping transition"
        )
        return None

    if not SessionStateMachine.can_transition(session.status, SessionState.LIVE):
        logger.error(
            f"Invalid state transition from {session.status} to LIVE for "
            f"session {session.session_id}"
        )
        return None

    from ._base import BaseService

    base_service = BaseService()
    updated_session = await base_service.update_session_state(session, SessionState.LIVE)
    logger.info(f"✅ Session {session.session_id} transitioned PUBLISHING -> LIVE")
    return updated_session


async def _update_session_with_dvr_urls(
    session: Session,
    mux_stream_id: str,
) -> Session | None:
    """Update session with DVR-enabled playback URLs from Mux asset.

    When the live stream becomes active, Mux creates an asset for DVR playback.
    This function fetches the asset's playback_id and updates the session's
    live_playback_url to enable DVR mode (full timeline scrubbing).

    Args:
        session: Session document to update
        mux_stream_id: Mux stream ID to get asset info from

    Returns:
        Updated session if successful, None otherwise
    """
    try:
        # Get live stream to find active asset ID
        mux_stream = mux_service.get_live_stream(mux_stream_id)
        active_asset_id = mux_stream.data.active_asset_id

        if not active_asset_id:
            logger.debug(
                f"No active asset for stream {mux_stream_id}, using stream playback_id for URLs"
            )
            return session

        # Get the playback_id from stream (asset playback_id is typically same)
        # For DVR-enabled URLs, we'll use the stream's playback_id initially
        # The webhook will update with asset's playback_id when ready
        playback_ids = mux_stream.data.playback_ids
        if not playback_ids:
            logger.warning(f"No playback IDs found for stream {mux_stream_id}")
            return session

        # Use first public playback_id
        playback_id = None
        for pb in playback_ids:
            if pb.policy == "public":
                playback_id = pb.id
                break
        if not playback_id:
            playback_id = playback_ids[0].id

        # Generate URLs
        config = get_app_environ_config()
        mux_stream_base_url = config.MUX_STREAM_BASE_URL
        live_playback_url = f"{mux_stream_base_url}/{playback_id}.m3u8"

        animated_url = mux_service.get_animated_url(playback_id)
        thumbnail_url = mux_service.get_thumbnail_url(playback_id, width=853, height=480, time=60)
        storyboard_url = mux_service.get_storyboard_url(playback_id)

        logger.info(
            f"🎬 Updating session {session.session_id} with playback URL: {live_playback_url}"
        )

        # Update session runtime
        if session.runtime and session.runtime.mux:
            session.runtime.mux.mux_active_asset_id = active_asset_id
        session.runtime.live_playback_url = live_playback_url
        session.runtime.animated_url = animated_url
        session.runtime.thumbnail_url = thumbnail_url
        session.runtime.storyboard_url = storyboard_url
        updates = {
            Session.runtime.live_playback_url: session.runtime.live_playback_url,
            Session.runtime.animated_url: session.runtime.animated_url,
            Session.runtime.thumbnail_url: session.runtime.thumbnail_url,
            Session.runtime.storyboard_url: session.runtime.storyboard_url,
        }
        if session.runtime and session.runtime.mux:
            updates[Session.runtime.mux.mux_active_asset_id] = active_asset_id

        await session.partial_update_session_with_version_check(
            updates,
            max_retry_on_conflicts=2,
        )

        return session

    except Exception as e:
        logger.error(
            f"Failed to update session {session.session_id} with DVR URLs: {e}",
            exc_info=True,
        )
        return session


async def delayed_stream_startup_check(
    session_id: str,
    mux_stream_id: str,
    delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
    max_retries: int = MAX_RETRIES,
    retry_delay_seconds: int = RETRY_DELAY_SECONDS,
) -> None:
    """Delayed startup check task for verifying Mux stream is active and transitioning to LIVE.

    This task:
    1. Waits for the initial delay
    2. Checks if the Mux live stream is active
    3. If active, updates session with DVR URLs, transitions to LIVE, and notifies External Live
    4. If not active, retries up to max_retries times with retry_delay between checks

    Args:
        session_id: Session ID to process
        mux_stream_id: Mux stream ID to check status for
        delay_seconds: Initial delay in seconds before first check (default: 30)
        max_retries: Maximum number of retry attempts (default: 10)
        retry_delay_seconds: Delay between retries in seconds (default: 30)
    """
    logger.info(
        f"⏱️  Starting delayed startup check for session {session_id}, "
        f"mux_stream_id={mux_stream_id}, delay={delay_seconds}s"
    )

    try:
        # Step 1: Wait for the initial delay
        await asyncio.sleep(delay_seconds)
        logger.info(
            f"⏱️  Initial delay complete for session {session_id}, checking Mux stream status"
        )

        for attempt in range(max_retries):
            # Step 2: Fetch current session state from database
            session = await Session.find_one(Session.session_id == session_id)
            if not session:
                logger.warning(f"Session {session_id} not found, startup check cancelled")
                return

            # Only proceed if session is still in PUBLISHING state
            if session.status != SessionState.PUBLISHING:
                if session.status == SessionState.LIVE:
                    logger.info(
                        f"Session {session_id} already transitioned to LIVE "
                        f"(likely by webhook), startup check complete"
                    )
                else:
                    logger.info(
                        f"Session {session_id} is no longer in PUBLISHING state "
                        f"(current: {session.status}), startup check cancelled"
                    )
                return

            # Step 3: Check Mux stream status
            try:
                mux_stream = mux_service.get_live_stream(mux_stream_id)
                stream_status = mux_stream.data.status
                logger.info(
                    f"Mux stream {mux_stream_id} status: {stream_status} "
                    f"(session {session_id}, attempt {attempt + 1}/{max_retries})"
                )

                # If stream is active, proceed with transition
                if stream_status == "active":
                    logger.info(
                        f"✅ Mux stream {mux_stream_id} is active, "
                        f"transitioning session {session_id} to LIVE"
                    )

                    # Step 4: Update session with DVR URLs
                    session = await _update_session_with_dvr_urls(session, mux_stream_id)
                    if not session:
                        logger.error(f"Failed to update session {session_id} with DVR URLs")
                        return

                    # Step 5: Call External Live admin/live/start BEFORE transitioning to LIVE
                    channel = await Channel.find_one(Channel.channel_id == session.channel_id)
                    if not channel:
                        logger.warning(
                            f"Channel not found for session {session_id}, "
                            f"channel_id={session.channel_id}"
                        )
                        return

                    external_live_post_id = await _call_external_live_start_live(session, channel)
                    if external_live_post_id:
                        # Store post_id in session config for later stop_live call
                        session.runtime.post_id = external_live_post_id
                        await session.partial_update_session_with_version_check(
                            {Session.runtime.post_id: session.runtime.post_id},
                            max_retry_on_conflicts=2,
                        )

                        logger.info(
                            f"✅ External Live start_live completed for session {session_id}, "
                            f"post_id={external_live_post_id}"
                        )

                    # Step 6: Transition session to LIVE
                    updated_session = await _transition_session_to_live(session)
                    if not updated_session:
                        logger.error(f"Failed to transition session {session_id} to LIVE")
                        return

                    logger.info(f"✅ Delayed startup check completed for session {session_id}")
                    return

            except Exception as e:
                logger.warning(
                    f"Failed to get Mux stream status for {mux_stream_id} "
                    f"(attempt {attempt + 1}/{max_retries}): {e}"
                )

            # Stream not active yet, wait and retry
            if attempt < max_retries - 1:
                logger.info(
                    f"Mux stream {mux_stream_id} not active yet, "
                    f"retrying in {retry_delay_seconds}s..."
                )
                await asyncio.sleep(retry_delay_seconds)

        # Exhausted all retries
        logger.warning(
            f"⚠️  Mux stream {mux_stream_id} did not become active after "
            f"{max_retries} attempts for session {session_id}. "
            f"Webhook will handle transition if stream becomes active later."
        )

    except Exception as e:
        logger.error(
            f"Error in delayed startup check for session {session_id}: {e}",
            exc_info=True,
        )


def schedule_delayed_startup_check(
    session_id: str,
    mux_stream_id: str,
    delay_seconds: int = DEFAULT_STARTUP_DELAY_SECONDS,
) -> asyncio.Task:
    """Schedule a delayed startup check task for a session.

    Creates an asyncio task that will run the delayed startup check after the
    specified delay. The task runs independently and does not block.

    Args:
        session_id: Session ID to process
        mux_stream_id: Mux stream ID to check status for
        delay_seconds: Initial delay in seconds before first check (default: 30)

    Returns:
        The created asyncio.Task for the startup check operation
    """
    task = asyncio.create_task(
        delayed_stream_startup_check(
            session_id=session_id,
            mux_stream_id=mux_stream_id,
            delay_seconds=delay_seconds,
        ),
        name=f"startup-{session_id}",
    )
    logger.info(
        f"📅 Scheduled delayed startup check task for session {session_id} (delay={delay_seconds}s)"
    )
    return task
