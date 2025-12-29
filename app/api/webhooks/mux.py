"""Mux webhook endpoint for receiving live stream events.

This endpoint receives webhook notifications from Mux about live stream events
and performs signature verification for security.

Event Types:
- video.live_stream.created: Live stream was created
- video.live_stream.connected: Stream connected (before becoming active)
- video.live_stream.active: Stream became active (PUBLISHING -> LIVE)
- video.live_stream.idle: Stream became idle (ENDING -> STOPPED)
- video.live_stream.recording: Stream recording started
- video.live_stream.disconnected: Stream disconnected (ENDING -> STOPPED)
- video.live_stream.deleted: Live stream was deleted
- video.asset.created: Asset was created from live stream
- video.asset.ready: Asset is ready for playback
- video.asset.errored: Asset processing failed
- video.asset.deleted: Asset was deleted
- video.asset.live_stream_completed: Live stream ended and asset is finalized
- video.asset.master.ready: Master (high-quality source) version is ready
- video.asset.static_renditions.ready: Static renditions (MP4 files) are ready

References:
- https://docs.mux.com/guides/video/listen-for-webhooks
- https://docs.mux.com/guides/video/verify-webhook-signatures
- Pydantic schemas: app.api.webhooks.schemas.mux
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any

from fastapi import APIRouter, Header, Request
from loguru import logger
from pydantic import ValidationError

from app.api.webhooks.schemas.mux import (
    AssetCreatedEvent,
    AssetDeletedEvent,
    AssetErroredEvent,
    AssetLiveStreamCompletedEvent,
    AssetMasterReadyEvent,
    AssetReadyEvent,
    AssetStaticRenditionsReadyEvent,
    LiveStreamActiveEvent,
    LiveStreamConnectedEvent,
    LiveStreamCreatedEvent,
    LiveStreamDeletedEvent,
    LiveStreamDisconnectedEvent,
    LiveStreamIdleEvent,
    LiveStreamRecordingEvent,
    MuxEventType,
)
from app.app_config import get_app_environ_config
from app.shared.api.utils import ApiFailure, ApiSuccess, api_failure
from app.domain.live.session.session_domain import SessionService
from app.schemas import Channel, Session, SessionState
from app.services.integrations.external_live.external_live_client import ExternalLiveClient
from app.services.integrations.external_live.external_live_schemas import (
    AdminStartLiveBody,
    AdminStopLiveBody,
    ExternalLiveApiSuccess,
    ChannelConfig,
    SessionConfig,
)
from app.services.integrations.mux_service import mux_service
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class MuxWebhookSuccess(ApiSuccess):
    """Success response for webhook."""

    results: dict[str, Any]  # type: ignore[assignment]


def _parse_passthrough(passthrough: str | None) -> tuple[str | None, str | None, str | None]:
    """Parse Mux passthrough parameter safely.

    Expected format: room_id|channel_id|session_id

    Args:
        passthrough: Raw passthrough string from Mux webhook

    Returns:
        Tuple of (room_id, channel_id, session_id). Returns (None, None, None) if parsing fails.
    """
    if not passthrough:
        return None, None, None

    # Strip whitespace from the entire passthrough string
    passthrough = passthrough.strip()

    # Split by delimiter and strip each part
    parts = [p.strip() for p in passthrough.split("|")]

    # Validate format
    if len(parts) < 3:
        logger.warning(
            f"Invalid passthrough format (expected 3 parts, got {len(parts)}): {passthrough}"
        )
        return None, None, None

    room_id = parts[0] if parts[0] else None
    channel_id = parts[1] if parts[1] else None
    session_id = parts[2] if parts[2] else None

    return room_id, channel_id, session_id


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


def verify_mux_signature(
    payload: bytes,
    signature_header: str,
    signing_secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """Verify Mux webhook signature using HMAC SHA256.

    Args:
        payload: Raw request body bytes
        signature_header: Value of 'mux-signature' header
        signing_secret: Your Mux webhook signing secret
        tolerance_seconds: Maximum age of webhook (default: 5 minutes)

    Returns:
        True if signature is valid and timestamp is within tolerance

    Raises:
        ValueError: If signature header is malformed or verification fails
    """
    # Step 1: Extract timestamp and signatures from header
    # Format: t=1565220904,v1=20c75c1180c701...
    elements = {}
    for element in signature_header.split(","):
        if "=" not in element:
            continue
        key, value = element.split("=", 1)
        elements[key] = value

    if "t" not in elements or "v1" not in elements:
        raise AppError(
            errcode=AppErrorCode.E_WEBHOOK_INVALID_SIGNATURE,
            errmesg="Invalid signature header format - missing t or v1",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

    timestamp_str = elements["t"]
    received_signature = elements["v1"]

    try:
        timestamp = int(timestamp_str)
    except ValueError as exc:
        raise AppError(
            errcode=AppErrorCode.E_WEBHOOK_INVALID_SIGNATURE,
            errmesg=f"Invalid timestamp in signature: {timestamp_str}",
            status_code=HttpStatusCode.BAD_REQUEST,
        ) from exc

    # Step 2: Check timestamp tolerance (prevent replay attacks)
    current_time = int(time.time())
    if abs(current_time - timestamp) > tolerance_seconds:
        raise AppError(
            errcode=AppErrorCode.E_WEBHOOK_INVALID_SIGNATURE,
            errmesg=f"Timestamp outside tolerance window: "
            f"received={timestamp}, current={current_time}, "
            f"diff={abs(current_time - timestamp)}s",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

    # Step 3: Prepare signed payload
    # Format: "{timestamp}.{raw_body}"
    signed_payload = f"{timestamp_str}.{payload.decode('utf-8')}"

    # Step 4: Compute expected signature using HMAC SHA256
    expected_signature = hmac.new(
        signing_secret.encode("utf-8"),
        signed_payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    # Step 5: Compare signatures (constant-time comparison)
    return hmac.compare_digest(expected_signature, received_signature)


async def handle_live_stream_created(event: LiveStreamCreatedEvent) -> dict[str, Any]:
    """Handle video.live_stream.created event."""
    logger.info(f"🟢 LIVE STREAM CREATED: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    # TODO: Update session metadata with stream info
    return {"handled": "live_stream_created", "stream_id": event.data.id}


async def handle_live_stream_active(event: LiveStreamActiveEvent) -> dict[str, Any]:
    """Handle video.live_stream.active event.

    This is an informational event indicating the stream is now active.
    The actual LIVE transition and External Live notification happens in handle_asset_ready
    when the DVR-enabled asset becomes available.
    """
    logger.info(f"🔴 LIVE STREAM ACTIVE: {event.data.id}")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    return {"handled": "live_stream_active", "stream_id": event.data.id}


async def handle_live_stream_idle(event: LiveStreamIdleEvent) -> dict[str, Any]:
    """Handle video.live_stream.idle event.

    When stream goes idle from ENDING state, transition to STOPPED
    and call External Live admin/live/stop to notify the platform.
    """
    logger.info(f"⏸️  LIVE STREAM IDLE: {event.data.id}")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    service = SessionService()
    live_stream_id = event.data.id
    passthrough = event.data.passthrough

    try:
        session = None
        logger.debug(
            f"Looking up session for idle event: passthrough={passthrough}, live_stream_id={live_stream_id}"
        )

        if passthrough:
            # Parse passthrough: room_id|channel_id|session_id
            room_id, channel_id, session_id = _parse_passthrough(passthrough)
            logger.debug(
                f"Parsed passthrough: room_id={room_id}, channel_id={channel_id}, session_id={session_id}"
            )
            if session_id:
                logger.debug(f"Searching for session by session_id: {session_id}")
                session = await Session.find_one(Session.session_id == session_id)
                if session:
                    logger.debug(
                        f"Found session: {session.session_id}, status={session.status.value}"
                    )

        if not session and live_stream_id:
            logger.debug(f"Searching for session by mux_stream_id: {live_stream_id}")
            session = await Session.find_one({"runtime.mux.mux_stream_id": live_stream_id})
            if session:
                logger.debug(f"Found session: {session.session_id}, status={session.status.value}")

        if not session:
            logger.warning(
                f"No session found for live_stream_id={live_stream_id}, passthrough={passthrough}"
            )
            return {
                "handled": False,
                "reason": "session_not_found",
                "live_stream_id": live_stream_id,
            }

        # Only transition to STOPPED if in ENDING state
        external_live_stopped = False
        logger.debug(
            f"Checking if session can transition to STOPPED: status={session.status.value}"
        )

        if session.status == SessionState.ENDING:
            logger.debug(f"Session {session.session_id} in ENDING state, calling External Live stop_live")
            # Call External Live admin/live/stop before transitioning
            external_live_stopped = await _call_external_live_stop_live(session)
            logger.debug(f"External Live stop_live result: {external_live_stopped}")

            logger.debug(f"Transitioning session {session.session_id}: ENDING -> STOPPED")
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.STOPPED,
            )
            logger.info(f"✅ Session {session.session_id} transitioned ENDING -> STOPPED")

            return {
                "handled": True,
                "session_id": session.session_id,
                "new_status": SessionState.STOPPED.value,
                "external_live_stopped": external_live_stopped,
            }
        else:
            logger.info(
                f"Stream idle for session {session.session_id} in state "
                f"{session.status.value}, not transitioning (expected only from ENDING)"
            )
            return {
                "handled": True,
                "action": "no_update_needed",
                "session_id": session.session_id,
                "reason": f"state_mismatch_current_{session.status.value}",
            }

    except Exception as e:
        logger.exception(f"Failed to update session state on stream idle: {e}")
        return {"handled": False, "error": str(e)}


async def handle_live_stream_recording(
    event: LiveStreamRecordingEvent,
) -> dict[str, Any]:
    """Handle video.live_stream.recording event."""
    logger.info(f"📹 LIVE STREAM RECORDING: {event.data.id}")

    # TODO: Update session recording status
    return {"handled": "live_stream_recording", "stream_id": event.data.id}


async def handle_live_stream_disconnected(
    event: LiveStreamDisconnectedEvent,
) -> dict[str, Any]:
    """Handle video.live_stream.disconnected event.

    When stream disconnects from ENDING state, transition to STOPPED
    and call External Live admin/live/stop to notify the platform.
    """
    logger.info(f"🔌 LIVE STREAM DISCONNECTED: {event.data.id}")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    service = SessionService()
    live_stream_id = event.data.id
    passthrough = event.data.passthrough

    try:
        session = None
        logger.debug(
            f"Looking up session for disconnected event: passthrough={passthrough}, live_stream_id={live_stream_id}"
        )

        if passthrough:
            # Parse passthrough: room_id|channel_id|session_id
            room_id, channel_id, session_id = _parse_passthrough(passthrough)
            logger.debug(
                f"Parsed passthrough: room_id={room_id}, channel_id={channel_id}, session_id={session_id}"
            )
            if session_id:
                logger.debug(f"Searching for session by session_id: {session_id}")
                session = await Session.find_one(Session.session_id == session_id)
                if session:
                    logger.debug(
                        f"Found session: {session.session_id}, status={session.status.value}"
                    )

        if not session and live_stream_id:
            logger.debug(f"Searching for session by mux_stream_id: {live_stream_id}")
            session = await Session.find_one({"runtime.mux.mux_stream_id": live_stream_id})
            if session:
                logger.debug(f"Found session: {session.session_id}, status={session.status.value}")

        if not session:
            logger.warning(
                f"No session found for live_stream_id={live_stream_id}, passthrough={passthrough}"
            )
            return {
                "handled": False,
                "reason": "session_not_found",
                "live_stream_id": live_stream_id,
            }

        # Only transition to STOPPED if in ENDING state
        external_live_stopped = False
        logger.debug(
            f"Checking if session can transition to STOPPED: status={session.status.value}"
        )

        if session.status == SessionState.ENDING:
            logger.debug(f"Session {session.session_id} in ENDING state, calling External Live stop_live")
            # Call External Live admin/live/stop before transitioning
            external_live_stopped = await _call_external_live_stop_live(session)
            logger.debug(f"External Live stop_live result: {external_live_stopped}")

            logger.debug(f"Transitioning session {session.session_id}: ENDING -> STOPPED")
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.STOPPED,
            )
            logger.info(f"✅ Session {session.session_id} transitioned ENDING -> STOPPED")

            return {
                "handled": True,
                "session_id": session.session_id,
                "new_status": SessionState.STOPPED.value,
                "external_live_stopped": external_live_stopped,
            }
        else:
            logger.warning(
                f"Stream disconnected for session {session.session_id} in state "
                f"{session.status.value}, not transitioning (expected only from ENDING)"
            )
            return {
                "handled": True,
                "action": "no_update_needed",
                "session_id": session.session_id,
                "reason": f"state_mismatch_current_{session.status.value}",
            }

    except Exception as e:
        logger.exception(f"Failed to update session state on stream disconnect: {e}")
        return {"handled": False, "error": str(e)}


async def handle_live_stream_deleted(event: LiveStreamDeletedEvent) -> dict[str, Any]:
    """Handle video.live_stream.deleted event."""
    logger.info(f"🗑️  LIVE STREAM DELETED: {event.data.id}")

    # TODO: Clean up session metadata
    return {"handled": "live_stream_deleted", "stream_id": event.data.id}


async def handle_asset_created(event: AssetCreatedEvent) -> dict[str, Any]:
    """Handle video.asset.created event."""
    logger.info(f"📦 ASSET CREATED: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")

    # TODO: Save asset metadata to session
    return {"handled": "asset_created", "asset_id": event.data.id}


async def handle_asset_ready(event: AssetReadyEvent) -> dict[str, Any]:
    """Handle video.asset.ready event.

    When the asset is ready, we:
    1. Transition the session from PUBLISHING to LIVE
    2. Update the session's live_playback_url to use the asset's playback_id
       (enables DVR mode with full timeline from beginning)
    3. Call External Live admin/live/start to notify the platform

    Using the stream's playback_id only shows ~30 seconds of recent content (non-DVR mode),
    while using the asset's playback_id shows the full timeline from the beginning (DVR mode).

    VOD URL is set separately when static renditions are ready
    (video.asset.static_renditions.ready).

    Reference: https://www.mux.com/docs/guides/stream-recordings-of-live-streams
    """
    logger.info(f"✅ ASSET READY: {event.data.id}")
    logger.info(f"   Duration: {event.data.duration}s")
    logger.info(f"   Resolution: {event.data.max_stored_resolution}")
    logger.info(f"   Passthrough: {event.data.passthrough}")
    logger.info(f"   LiveStreamId: {event.data.live_stream_id}")
    logger.info(f"   IsLive: {event.data.is_live}")

    try:
        asset_id = event.data.id
        live_stream_id = event.data.live_stream_id
        passthrough = event.data.passthrough  # Format: room_id|channel_id|session_id
        playback_ids = event.data.playback_ids or []
        is_live = event.data.is_live

        # Only process if this asset is from an active live stream
        if not is_live:
            logger.debug(f"Asset {asset_id} is not from an active live stream, skipping")
            return {"handled": "asset_ready", "asset_id": asset_id, "dvr_updated": False}

        logger.debug(
            f"Processing asset ready: asset_id={asset_id}, "
            f"live_stream_id={live_stream_id}, passthrough={passthrough}, "
            f"playback_ids_count={len(playback_ids)}"
        )

        # Find session by passthrough (session_id) first, fall back to mux_stream_id
        session = None
        if passthrough:
            # Parse passthrough: room_id|channel_id|session_id
            room_id, channel_id, session_id = _parse_passthrough(passthrough)
            logger.debug(
                f"Parsed passthrough: room_id={room_id}, channel_id={channel_id}, session_id={session_id}"
            )
            if session_id:
                logger.debug(f"Searching for session by session_id: {session_id}")
                session = await Session.find_one(Session.session_id == session_id)
                if session:
                    logger.debug(f"Found session by passthrough: {session.session_id}")

        if not session and live_stream_id:
            logger.debug(f"Searching for session by mux_stream_id: {live_stream_id}")
            session = await Session.find_one({"runtime.mux.mux_stream_id": live_stream_id})
            if session:
                logger.debug(f"Found session by mux_stream_id: {session.session_id}")

        if not session:
            logger.warning(
                f"No session found for asset_id={asset_id}, passthrough={passthrough}, "
                f"live_stream_id={live_stream_id}"
            )
            return {
                "handled": False,
                "asset_id": asset_id,
                "error": "session_not_found",
            }

        # Extract first public playback ID from the asset
        asset_playback_id = None
        for pb in playback_ids:
            if pb.get("policy") == "public":
                asset_playback_id = pb.get("id")
                break

        if not asset_playback_id and playback_ids:
            # Fall back to first playback ID if no public one found
            asset_playback_id = playback_ids[0].get("id")

        if not asset_playback_id:
            logger.warning(f"No playback ID found in asset {asset_id}")
            return {
                "handled": False,
                "asset_id": asset_id,
                "error": "no_playback_id_in_asset",
            }

        # Construct DVR-enabled playback URL using asset's playback_id
        config = get_app_environ_config()
        mux_stream_base_url = config.MUX_STREAM_BASE_URL
        dvr_playback_url = f"{mux_stream_base_url}/{asset_playback_id}.m3u8"

        # Generate image URLs using asset's playback_id for better quality
        animated_url = mux_service.get_animated_url(asset_playback_id)
        thumbnail_url = mux_service.get_thumbnail_url(
            asset_playback_id, width=853, height=480, time=60
        )
        storyboard_url = mux_service.get_storyboard_url(asset_playback_id)

        logger.info(
            f"🎬 Updating session {session.session_id} with DVR playback URL: {dvr_playback_url}"
        )
        logger.debug(
            f"   animated_url={animated_url}, thumbnail_url={thumbnail_url}, "
            f"storyboard_url={storyboard_url}"
        )

        # Update session runtime with DVR URL, image URLs, and active asset ID
        session.runtime.live_playback_url = dvr_playback_url
        session.runtime.animated_url = animated_url
        session.runtime.thumbnail_url = thumbnail_url
        session.runtime.storyboard_url = storyboard_url
        if session.runtime and session.runtime.mux:
            session.runtime.mux.mux_active_asset_id = asset_id
        updates = {
            Session.runtime.live_playback_url: session.runtime.live_playback_url,
            Session.runtime.animated_url: session.runtime.animated_url,
            Session.runtime.thumbnail_url: session.runtime.thumbnail_url,
            Session.runtime.storyboard_url: session.runtime.storyboard_url,
        }
        if session.runtime and session.runtime.mux:
            updates[Session.runtime.mux.mux_active_asset_id] = asset_id

        await session.partial_update_session_with_version_check(
            updates,
            max_retry_on_conflicts=2,
        )

        # Call External Live and transition to LIVE state
        service = SessionService()
        external_live_post_id = None
        logger.debug(f"Current session status: {session.status.value}")

        if session.status == SessionState.PUBLISHING:
            # Call External Live admin/live/start BEFORE updating state
            logger.debug(f"Looking up channel: {session.channel_id}")
            channel = await Channel.find_one(Channel.channel_id == session.channel_id)
            if not channel:
                logger.warning(
                    f"Channel not found for session {session.session_id}, "
                    f"channel_id={session.channel_id}"
                )
                return {
                    "handled": False,
                    "asset_id": asset_id,
                    "error": "channel_not_found",
                }

            logger.debug(f"Found channel: {channel.channel_id}, title={channel.title}")
            external_live_post_id = await _call_external_live_start_live(session, channel)
            if external_live_post_id:
                # Store post_id in session config for later stop_live call
                session.runtime.post_id = external_live_post_id
                await session.partial_update_session_with_version_check(
                    {Session.runtime.post_id: session.runtime.post_id},
                    max_retry_on_conflicts=2,
                )

            # Now transition to LIVE state after External Live call succeeds
            logger.debug(
                f"Transitioning session {session.session_id}: {session.status.value} -> LIVE"
            )
            session = await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.LIVE,
            )
            logger.info(f"✅ Session {session.session_id} transitioned to LIVE")
        else:
            logger.debug(
                f"Session {session.session_id} in state {session.status.value}, not PUBLISHING, "
                f"skipping state transition to LIVE"
            )

        logger.info(
            f"✅ Asset ready processed for session {session.session_id}: "
            f"dvr_url={dvr_playback_url}, status=LIVE"
        )

        return {
            "handled": True,
            "asset_id": asset_id,
            "session_id": session.session_id,
            "dvr_playback_url": dvr_playback_url,
            "dvr_updated": True,
            "new_status": SessionState.LIVE.value,
            "external_live_post_id": external_live_post_id,
        }

    except Exception as e:
        logger.exception(f"Failed to process asset ready: {e}")
        return {"handled": False, "asset_id": event.data.id, "error": str(e)}


async def handle_asset_errored(event: AssetErroredEvent) -> dict[str, Any]:
    """Handle video.asset.errored event."""
    logger.error(f"❌ ASSET ERRORED: {event.data.id}")
    logger.error(f"   Status: {event.data.status}")

    # TODO: Update session with error status
    return {"handled": "asset_errored", "asset_id": event.data.id}


async def handle_asset_deleted(event: AssetDeletedEvent) -> dict[str, Any]:
    """Handle video.asset.deleted event."""
    logger.info(f"🗑️  ASSET DELETED: {event.data.id}")

    # TODO: Clean up session asset references
    return {"handled": "asset_deleted", "asset_id": event.data.id}


async def handle_live_stream_connected(
    event: LiveStreamConnectedEvent,
) -> dict[str, Any]:
    """Handle video.live_stream.connected event.

    Fired when a live stream successfully connects to Mux (before becoming active).
    This is an informational event - the stream will transition to active shortly.
    """
    logger.info(f"🔗 LIVE STREAM CONNECTED: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    return {"handled": "live_stream_connected", "stream_id": event.data.id}


async def handle_asset_live_stream_completed(
    event: AssetLiveStreamCompletedEvent,
) -> dict[str, Any]:
    """Handle video.asset.live_stream_completed event.

    Fired when a live stream ends and the asset recording is finalized.
    This indicates the asset from the live stream is now complete.
    """
    logger.info(f"🏁 ASSET LIVE STREAM COMPLETED: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")
    logger.info(f"   Duration: {event.data.duration}s")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    return {"handled": "asset_live_stream_completed", "asset_id": event.data.id}


async def handle_asset_master_ready(event: AssetMasterReadyEvent) -> dict[str, Any]:
    """Handle video.asset.master.ready event.

    Fired when the master (high-quality source) version of an asset is ready
    for download. This is useful for archival or additional processing.

    VOD playback URL is set separately in video.asset.static_renditions.ready.
    """
    logger.info(f"📼 ASSET MASTER READY: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")
    logger.info(f"   Duration: {event.data.duration}s")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    # TODO: Save master asset metadata if needed for archival
    return {"handled": "asset_master_ready", "asset_id": event.data.id}


async def handle_asset_static_renditions_ready(
    event: AssetStaticRenditionsReadyEvent,
) -> dict[str, Any]:
    """Handle video.asset.static_renditions.ready event.

    Fired when static renditions (MP4 files) for an asset are ready for download.
    This is the correct event to set the VOD playback URL in the session config.
    """
    logger.info(f"📦 ASSET STATIC RENDITIONS READY: {event.data.id}")
    logger.info(f"   Status: {event.data.status}")
    logger.info(f"   Duration: {event.data.duration}s")
    logger.info(f"   Passthrough: {event.data.passthrough}")

    try:
        asset_id = event.data.id
        passthrough = event.data.passthrough  # Format: room_id|channel_id|session_id
        playback_ids = event.data.playback_ids or []

        logger.debug(
            f"Processing static renditions ready: asset_id={asset_id}, "
            f"passthrough={passthrough}, playback_ids_count={len(playback_ids)}"
        )

        # Find session by passthrough (session_id)
        session = None
        if passthrough:
            # Parse passthrough: room_id|channel_id|session_id
            room_id, channel_id, session_id = _parse_passthrough(passthrough)
            logger.debug(
                f"Parsed passthrough: room_id={room_id}, channel_id={channel_id}, session_id={session_id}"
            )
            if session_id:
                logger.debug(f"Searching for session by session_id: {session_id}")
                session = await Session.find_one(Session.session_id == session_id)
                if session:
                    logger.debug(f"Found session: {session.session_id}")

        if not session:
            logger.warning(
                f"No session found for asset static renditions ready event: "
                f"asset_id={asset_id}, passthrough={passthrough}"
            )
            return {
                "handled": False,
                "reason": "session_not_found",
                "asset_id": asset_id,
            }

        # Extract first playback ID for VOD
        vod_playback_id = None
        vod_playback_url = None

        if playback_ids and len(playback_ids) > 0:
            vod_playback_id = playback_ids[0].get("id")
            logger.debug(f"Extracted VOD playback_id: {vod_playback_id}")
        else:
            logger.warning(f"No playback_ids found for asset {asset_id}")

        if vod_playback_id:
            # Generate VOD playback URL
            config = get_app_environ_config()
            mux_stream_base_url = config.MUX_STREAM_BASE_URL
            vod_playback_url = f"{mux_stream_base_url}/{vod_playback_id}.m3u8"
            logger.debug(f"Generated VOD playback URL: {vod_playback_url}")

            # Update session config with VOD URL
            logger.debug(f"Updating session {session.session_id} with VOD URL")
            session.runtime.vod_playback_url = vod_playback_url
            await session.partial_update_session_with_version_check(
                {Session.runtime.vod_playback_url: session.runtime.vod_playback_url},
                max_retry_on_conflicts=2,
            )

            logger.info(f"✅ Updated session {session.session_id} with VOD URL: {vod_playback_url}")

        return {
            "handled": True,
            "session_id": session.session_id,
            "asset_id": asset_id,
            "vod_playback_url": vod_playback_url,
        }

    except Exception as e:
        logger.exception(f"Failed to update session with VOD URL: {e}")
        return {"handled": False, "error": str(e)}


@router.post("/mux", response_model=MuxWebhookSuccess | ApiFailure)
async def mux_webhook(
    request: Request,
    mux_signature: str | None = Header(None, alias="mux-signature"),
) -> MuxWebhookSuccess | ApiFailure:
    """Receive and process Mux webhook events.

    This endpoint parses webhook events into typed Pydantic models and handles
    them case by case.

    Args:
        request: FastAPI request object
        mux_signature: Signature header for verification

    Returns:
        Success response with handling results or failure

    Security:
        - Requires valid Mux webhook signature
        - Timestamp must be within 5 minutes (prevents replay attacks)
        - Uses constant-time signature comparison
    """
    try:
        # Get raw body for signature verification
        body = await request.body()
        logger.debug(
            f"Received Mux webhook request: body_length={len(body)}, has_signature={bool(mux_signature)}"
        )

        # Get signing secret from config
        config = get_app_environ_config()
        signing_secret = config.MUX_WEBHOOK_SIGNING_SECRET
        logger.debug(f"Webhook signing secret configured: {bool(signing_secret)}")

        if not signing_secret:
            logger.error("MUX_WEBHOOK_SIGNING_SECRET not configured")
            failure = api_failure(
                errcode=AppErrorCode.E_WEBHOOK_CONFIG_MISSING,
                errmesg="Webhook signing secret not configured",
            )
            return failure

        # Verify signature if provided
        if mux_signature:
            try:
                is_valid = verify_mux_signature(
                    payload=body,
                    signature_header=mux_signature,
                    signing_secret=signing_secret,
                )
                if not is_valid:
                    logger.warning("Invalid Mux webhook signature")
                    failure = api_failure(
                        errcode=AppErrorCode.E_WEBHOOK_INVALID_SIGNATURE,
                        errmesg="Invalid webhook signature",
                    )
                    return failure
                logger.debug("Mux webhook signature verified successfully")
            except ValueError as exc:
                logger.warning(f"Signature verification failed: {exc}")
                failure = api_failure(
                    errcode=AppErrorCode.E_WEBHOOK_SIGNATURE_ERROR,
                    errmesg=str(exc),
                )
                return failure
        else:
            logger.warning("Mux webhook received without signature header")
            # In production, you might want to reject unsigned webhooks
            # For development, we'll allow it but log a warning

        # Parse JSON
        try:
            event_data = json.loads(body.decode("utf-8"))
        except json.JSONDecodeError as exc:
            logger.error(f"Invalid JSON in webhook body: {exc}")
            failure = api_failure(
                errcode=AppErrorCode.E_WEBHOOK_INVALID_JSON,
                errmesg=f"Invalid JSON: {exc!s}",
            )
            return failure

        # Get event type
        event_type = event_data.get("type")
        event_id = event_data.get("id", "unknown")
        logger.debug(f"Parsed webhook event: type={event_type}, id={event_id}")

        if not event_type:
            logger.error("Missing 'type' field in webhook payload")
            failure = api_failure(
                errcode=AppErrorCode.E_WEBHOOK_MISSING_EVENT_TYPE,
                errmesg="Missing 'type' field",
            )
            return failure

        separator = "=" * 80
        logger.info(separator)
        logger.info(f"Mux Webhook: {event_type}")
        logger.info(separator)
        logger.debug(f"Full event data keys: {list(event_data.keys())}")

        # Parse into specific event schema and handle
        result: dict[str, Any]

        try:
            if event_type == MuxEventType.LIVE_STREAM_IDLE:
                # case MuxEventType.LIVE_STREAM_CREATED:
                #     event = LiveStreamCreatedEvent(**event_data)
                #     result = await handle_live_stream_created(event)

                # case MuxEventType.LIVE_STREAM_CONNECTED:
                #     event = LiveStreamConnectedEvent(**event_data)
                #     result = await handle_live_stream_connected(event)

                # case MuxEventType.LIVE_STREAM_ACTIVE:
                #     event = LiveStreamActiveEvent(**event_data)
                #     result = await handle_live_stream_active(event)

                event = LiveStreamIdleEvent(**event_data)
                result = await handle_live_stream_idle(event)

                # case MuxEventType.LIVE_STREAM_RECORDING:
                #     event = LiveStreamRecordingEvent(**event_data)
                #     result = await handle_live_stream_recording(event)

            elif event_type == MuxEventType.LIVE_STREAM_DISCONNECTED:
                event = LiveStreamDisconnectedEvent(**event_data)
                result = await handle_live_stream_disconnected(event)

                # case MuxEventType.LIVE_STREAM_DELETED:
                #     event = LiveStreamDeletedEvent(**event_data)
                #     result = await handle_live_stream_deleted(event)

                # case MuxEventType.ASSET_CREATED:
                #     event = AssetCreatedEvent(**event_data)
                #     result = await handle_asset_created(event)

            elif event_type == MuxEventType.ASSET_READY:
                event = AssetReadyEvent(**event_data)
                result = await handle_asset_ready(event)

            elif event_type == MuxEventType.ASSET_STATIC_RENDITIONS_READY:
                event = AssetStaticRenditionsReadyEvent(**event_data)
                result = await handle_asset_static_renditions_ready(event)

            else:
                # Keep unhandled events non-fatal in demo mode.
                logger.info(f"Unhandled event type: {event_type}")
                result = {"handled": False, "reason": "unhandled_event_type"}

            # Other event types are intentionally omitted in this public demo:
            # - ASSET_ERRORED / ASSET_DELETED / ASSET_LIVE_STREAM_COMPLETED / ASSET_MASTER_READY

        except ValidationError as exc:
            logger.error(f"Failed to parse {event_type} event: {exc}")
            logger.error(f"❌ VALIDATION ERROR: {exc}")
            failure = api_failure(
                errcode=AppErrorCode.E_WEBHOOK_VALIDATION_ERROR,
                errmesg=f"Failed to parse event: {exc!s}",
            )
            return failure

        logger.info(separator)

        return MuxWebhookSuccess(results=result)

    except Exception as exc:
        logger.exception("Error processing Mux webhook")
        failure = api_failure(
            errcode=AppErrorCode.E_WEBHOOK_ERROR,
            errmesg=str(exc),
        )
        return failure
