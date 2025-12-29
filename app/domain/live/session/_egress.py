"""LiveKit egress operations for session management."""

from urllib.parse import urlencode, urlparse

from livekit import api
from loguru import logger

from app.app_config import get_app_environ_config
from app.schemas import MuxPlaybackId, Session, SessionRuntime, SessionState
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from ._base import BaseService
from ._egress_cleanup import schedule_delayed_cleanup
from ._egress_startup import schedule_delayed_startup_check
from ._sessions import SessionOperations
from .session_models import LiveStreamStartResponse


class EgressOperations(BaseService):
    """LiveKit egress-related operations with Mux livestream integration."""

    def __init__(self):
        """Initialize EgressOperations with session operations."""
        super().__init__()
        self._sessions = SessionOperations()

    async def _abort_and_recreate_session(self, session: Session) -> Session:
        """Abort current session and create a new READY session.

        When a session is not in READY state but we need to start a live stream,
        this method:
        1. Transitions the session to ABORTED (if not already terminal)
        2. Then to STOPPED (terminal state)
        3. Creates a new READY session using the same room_id

        Args:
            session: The session to abort and recreate

        Returns:
            New Session in READY state

        Raises:
            AppError: If channel is not found or inactive
        """
        from .session_state_machine import SessionStateMachine

        original_status = session.status
        logger.info(
            f"Aborting session {session.session_id} in state {original_status} "
            f"and creating new session for room {session.room_id}"
        )

        updated_session = session

        # If already in terminal state, skip state transitions
        if SessionStateMachine.is_terminal(session.status):
            logger.info(f"Session {session.session_id} already in terminal state {session.status}")
        else:
            # Transition to ABORTED first (if valid), then to STOPPED
            if SessionStateMachine.can_transition(session.status, SessionState.ABORTED):
                updated_session = await self.update_session_state(session, SessionState.ABORTED)
                logger.info(f"Session {session.session_id} transitioned to ABORTED")

            # If in ABORTED, transition to STOPPED
            if updated_session.status == SessionState.ABORTED:
                updated_session = await self.update_session_state(
                    updated_session, SessionState.STOPPED
                )
                logger.info(f"Session {session.session_id} transitioned to STOPPED")
            # If can transition to CANCELLED (from IDLE, READY, PUBLISHING), do that
            elif SessionStateMachine.can_transition(session.status, SessionState.CANCELLED):
                updated_session = await self.update_session_state(session, SessionState.CANCELLED)
                logger.info(f"Session {session.session_id} transitioned to CANCELLED")

        if not updated_session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found after state update: {session.room_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Create new session from terminal state
        await self._sessions.recreate_session_from_terminal(terminal_session=updated_session)

        # Fetch the new session document
        new_session = await self._get_active_session_by_room_id(updated_session.room_id)
        if not new_session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"New session not found after recreation: {updated_session.room_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        logger.info(
            f"Created new READY session {new_session.session_id} "
            f"(old session {updated_session.session_id} was {original_status})"
        )

        return new_session

    async def start_live(
        self,
        room_name: str,
        layout: str = "speaker",
        referer: str | None = None,
        base_path: str | None = None,
        width: int = 1920,
        height: int = 1080,
        is_mobile: bool = False,
    ) -> LiveStreamStartResponse:
        """Start live streaming by creating Mux livestream and setting up LiveKit egress.

        This method:
        1. Creates a Mux livestream to get RTMP endpoint
        2. Starts LiveKit room composite egress to stream to Mux
        3. Updates session state to LIVE
        4. Stores egress info in session config
        5. Returns egress info and Mux stream data

        Args:
            room_name: Room name (also the room_id) to start egress for
            layout: Layout for the composite (default: "speaker")
            referer: HTTP Referer header to use as fallback for frontend base URL
            base_path: Frontend base path for recording URL (e.g., '/demo')
            width: Video width in pixels (default: 1920)
            height: Video height in pixels (default: 1080)
            is_mobile: Whether the request is from a mobile app (default: False)

        Returns:
            LiveStreamStartResponse with egress and Mux stream information

        Raises:
            AppError: If room doesn't exist or stream already in progress
            ValueError: If state transition is invalid
            Exception: If Mux or LiveKit API calls fail

        Example:
            result = await egress.start_live(
                room_name="my-livestream",
                layout="grid"
            )
            egress_id = result.egress_id
            config = get_app_environ_config()
            playback_url = f"{config.MUX_STREAM_BASE_URL}/{result.mux_playback_ids[0].id}.m3u8"
        """
        logger.info(f"Starting live stream for room={room_name} with layout={layout}")

        # Get session and verify it exists
        session = await self._get_active_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Check if stream is already in progress (PUBLISHING or LIVE)
        if session.status in (SessionState.PUBLISHING, SessionState.LIVE):
            logger.info(
                f"Live stream already in progress for room={room_name}, "
                f"status={session.status}. Returning existing stream data (idempotent)."
            )
            # Idempotent: return existing egress data from session config
            config = session.runtime

            egress_id = config.livekit.egress_id if config.livekit else None
            mux_stream_id = config.mux.mux_stream_id if config.mux else None
            mux_stream_key = config.mux.mux_stream_key if config.mux else None
            mux_rtmp_url = config.mux.mux_rtmp_url if config.mux else None
            mux_playback_ids = config.mux.mux_playback_ids if config.mux else None

            if egress_id and mux_stream_id and mux_stream_key and mux_rtmp_url:
                return LiveStreamStartResponse(
                    egress_id=egress_id,
                    mux_stream_id=mux_stream_id,
                    mux_stream_key=mux_stream_key,
                    mux_rtmp_url=mux_rtmp_url,
                    mux_playback_ids=mux_playback_ids or [],
                )

            # If we don't have complete egress data, treat as error
            raise AppError(
                errcode=AppErrorCode.E_LIVE_STREAM_IN_PROGRESS,
                errmesg=f"Live stream in progress but missing egress data for room: {room_name}",
                status_code=HttpStatusCode.CONFLICT,
            )

        # Handle non-READY states: abort and recreate session
        if session.status != SessionState.READY:
            logger.info(
                f"Session {room_name} is in {session.status} state, "
                f"aborting and creating new session"
            )
            session = await self._abort_and_recreate_session(session)

        mux_stream_id: str | None = None

        try:
            # Step 1: Create Mux livestream
            logger.info(f"Creating Mux livestream for room={room_name}")
            mux_response = self.mux.create_live_stream(
                playback_policy="public",
                new_asset_settings=True,
                passthrough=f"{session.user_id}|{session.channel_id}|{session.session_id}",
            )

            mux_stream = mux_response.data
            mux_stream_id = mux_stream.id
            mux_stream_key = mux_stream.stream_key

            # Get config for egress method selection and Mux settings
            cfg = get_app_environ_config()

            # Mux RTMP endpoint (base URL + /app path)
            mux_rtmp_url = f"{cfg.MUX_RTMP_INGEST_BASE_URL}/app"

            logger.info(f"Created Mux stream: stream_id={mux_stream_id}, rtmp_url={mux_rtmp_url}")

            # Step 2: Start LiveKit egress to stream to Mux
            # Build the full RTMP URL with stream key
            rtmp_url = f"{mux_rtmp_url}/{mux_stream_key}"

            if cfg.USE_WEB_EGRESS:
                # Web egress uses a custom recording page for capturing room content
                logger.info("Starting LiveKit web egress to Mux RTMP endpoint")

                # Create recorder token for web egress
                recorder_token = self.livekit.create_recorder_token(room=room_name)

                # Get the LiveKit WebSocket URL for the client
                livekit_ws_url = cfg.LIVEKIT_URL
                if not livekit_ws_url:
                    raise AppError(
                        errcode=AppErrorCode.E_INVALID_REQUEST,
                        errmesg="LIVEKIT_URL must be configured",
                        status_code=HttpStatusCode.BAD_REQUEST,
                    )

                # Construct recording page URL
                recording_params = urlencode(
                    {
                        "token": recorder_token,
                        "livekit_url": livekit_ws_url,
                    }
                )
                # Use FRONTEND_BASE_URL from config, fallback to referer origin
                frontend_base_url = cfg.FRONTEND_BASE_URL
                if not frontend_base_url:
                    if not referer:
                        raise AppError(
                            errcode=AppErrorCode.E_INVALID_REQUEST,
                            errmesg="FRONTEND_BASE_URL must be configured or Referer header must be provided",
                            status_code=HttpStatusCode.BAD_REQUEST,
                        )
                    # Extract origin from referer (scheme + host)
                    parsed = urlparse(referer)
                    frontend_base_url = f"{parsed.scheme}://{parsed.netloc}"

                # Use mobile recording path if platform is mobile
                recording_path = (
                    cfg.FRONTEND_MOBILE_RECORDING_PATH if is_mobile else cfg.FRONTEND_RECORDING_PATH
                )
                recording_url = (
                    f"{frontend_base_url}{base_path or ''}{recording_path}?{recording_params}"
                )

                logger.info(
                    f"Recording page URL: {recording_url.replace(recorder_token, '[REDACTED]')}"
                )

                # Create web egress request with custom encoding
                # NOTE: there's a bug in LiveKit that `preset` must be set to make `advanced` work
                egress_request = api.WebEgressRequest(
                    url=recording_url,
                    preset=api.EncodingOptionsPreset.H264_1080P_60,
                    advanced=api.EncodingOptions(
                        width=width,
                        height=height,
                        framerate=60,
                        video_bitrate=cfg.LIVEKIT_EGRESS_VIDEO_BITRATE,
                        audio_bitrate=192,
                        audio_frequency=48000,
                    ),
                    stream_outputs=[
                        api.StreamOutput(
                            protocol=api.StreamProtocol.RTMP,
                            urls=[rtmp_url],
                        )
                    ],
                )

                # Start the web egress
                egress_info = await self.livekit.start_web_egress(egress_request)
            else:
                # Room composite egress uses LiveKit's built-in compositor
                logger.info("Starting LiveKit room composite egress to Mux RTMP endpoint")

                # Create room composite egress request with custom encoding
                egress_request = api.RoomCompositeEgressRequest(
                    room_name=room_name,
                    layout=layout,
                    advanced=api.EncodingOptions(
                        width=width,
                        height=height,
                        framerate=60,
                        video_bitrate=cfg.LIVEKIT_EGRESS_VIDEO_BITRATE,
                        audio_bitrate=192,
                        audio_frequency=48000,
                    ),
                    stream_outputs=[
                        api.StreamOutput(
                            protocol=api.StreamProtocol.RTMP,
                            urls=[rtmp_url],
                        )
                    ],
                )

                # Start the room composite egress
                egress_info = await self.livekit.start_room_composite_egress(egress_request)

            egress_id = egress_info.egress_id

            logger.info(f"Started LiveKit egress: egress_id={egress_id} for room={room_name}")

            # Step 3: Build playback IDs list
            mux_playback_ids = [
                MuxPlaybackId(id=pb.id, policy=pb.policy) for pb in (mux_stream.playback_ids or [])
            ]

            # Step 4: Generate Mux URLs from playback ID
            # Use the first playback ID for generating URLs
            # Note: This initial URL uses the stream's playback_id (non-DVR mode, ~30s timeline).
            # When the asset becomes ready (video.asset.ready webhook), the live_playback_url
            # will be updated to use the asset's playback_id, enabling DVR mode with full
            # timeline scrubbing from the beginning of the stream.
            # Reference: https://www.mux.com/docs/guides/stream-recordings-of-live-streams
            playback_id = mux_playback_ids[0].id if mux_playback_ids else None
            live_playback_url = None
            animated_url = None
            thumbnail_url = None
            storyboard_url = None

            if playback_id:
                # Initial HLS playback URL (non-DVR mode)
                # Will be updated to DVR-enabled URL when video.asset.ready webhook fires
                config = get_app_environ_config()
                mux_stream_base_url = config.MUX_STREAM_BASE_URL
                live_playback_url = f"{mux_stream_base_url}/{playback_id}.m3u8"

                # Generate preview URLs using Mux API helpers
                animated_url = self.mux.get_animated_url(playback_id, width=640, fps=5)
                thumbnail_url = self.mux.get_thumbnail_url(
                    playback_id, width=853, height=480, time=60
                )
                storyboard_url = self.mux.get_storyboard_url(playback_id)

                logger.info(
                    f"Generated Mux URLs for playback_id={playback_id}: live={live_playback_url}, "
                    f"animated={animated_url}, thumbnail={thumbnail_url}, storyboard={storyboard_url}"
                )

            # Step 5: Update session config with egress information
            # At this point, mux_stream_id is guaranteed to be a string (not None)
            assert mux_stream_id is not None

            from app.schemas.session_runtime import LiveKitRuntime, MuxRuntime

            livekit_config = SessionRuntime(
                livekit=LiveKitRuntime(egress_id=egress_id),
                mux=MuxRuntime(
                    mux_stream_id=mux_stream_id,
                    mux_stream_key=mux_stream_key,
                    mux_rtmp_url=mux_rtmp_url,
                    mux_playback_ids=mux_playback_ids,
                ),
                live_playback_url=live_playback_url,
                vod_playback_url=None,  # VOD URL will be available after stream ends
                animated_url=animated_url,
                thumbnail_url=thumbnail_url,
                storyboard_url=storyboard_url,
            )

            # Update session with new config
            session.runtime = livekit_config

            await session.partial_update_session_with_version_check(
                {Session.runtime: session.runtime},
                max_retry_on_conflicts=2,
            )

            # Step 6: Update session state to PUBLISHING
            # Note: State will transition to LIVE when Mux webhook confirms stream is active
            await self.update_session_state(session, SessionState.PUBLISHING)
            logger.info(
                f"Session {session.room_id} state updated to PUBLISHING with egress_id={egress_id}"
            )

            # Schedule delayed startup check to verify stream becomes active and transition to LIVE
            # This will periodically check Mux stream status and transition to LIVE when active
            schedule_delayed_startup_check(
                session_id=session.session_id,
                mux_stream_id=mux_stream_id,
            )

            # Step 7: Build and return response
            result = LiveStreamStartResponse(
                egress_id=egress_id,
                mux_stream_id=mux_stream_id,
                mux_stream_key=mux_stream_key,
                mux_rtmp_url=mux_rtmp_url,
                mux_playback_ids=mux_playback_ids,
            )

            logger.info(f"Live stream started successfully for room={room_name}")
            return result

        except Exception as e:
            logger.error(
                f"Failed to start live stream for room={room_name}: {e}",
                exc_info=True,
            )
            # Clean up if we created a Mux stream but egress failed
            if mux_stream_id is not None:
                try:
                    self.mux.delete_live_stream(mux_stream_id)
                    logger.info(f"Cleaned up Mux stream {mux_stream_id} after failure")
                except Exception as cleanup_error:
                    logger.error(f"Failed to cleanup Mux stream {mux_stream_id}: {cleanup_error}")
            raise

    async def end_live(
        self,
        room_name: str,
        egress_id: str,
        mux_stream_id: str,
    ) -> None:
        """End live streaming by stopping LiveKit egress and signaling Mux stream complete.

        This method:
        1. Stops the LiveKit egress
        2. Signals Mux that the livestream is complete
        3. Updates session state to ENDING

        Args:
            room_name: Room name (also the room_id) to end streaming for
            egress_id: LiveKit egress ID to stop
            mux_stream_id: Mux stream ID to complete

        Raises:
            AppError: If room doesn't exist
            ValueError: If state transition is invalid
            Exception: If LiveKit or Mux API calls fail

        Example:
            await egress.end_live(
                room_name="my-livestream",
                egress_id="EG_...",
                mux_stream_id="..."
            )
        """
        logger.info(
            f"Ending live stream for room={room_name}, egress_id={egress_id}, mux_stream_id={mux_stream_id}"
        )

        # Get session and verify it exists
        session = await self._get_active_session_by_room_id(room_name)
        if not session:
            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Room not found: {room_name}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        # Verify session is in LIVE state (stream must be active)
        if session.status != SessionState.LIVE:
            logger.warning(
                f"Cannot end live stream: session must be in LIVE state, "
                f"current state: {session.status}"
            )
            # Allow transition from other states for now, but log warning
            # raise ValueError(
            #     f"Cannot end live stream: session must be in LIVE state, "
            #     f"current state: {session.status}"
            # )

        errors = []

        try:
            # Step 1: Stop LiveKit egress
            logger.info(f"Stopping LiveKit egress: egress_id={egress_id}")
            await self.livekit.stop_egress(egress_id)
            logger.info(f"Successfully stopped LiveKit egress: {egress_id}")

        except Exception as e:
            error_str = str(e)
            # Check if egress already completed - this is not an error
            if (
                "EGRESS_COMPLETE" in error_str
                or "EGRESS_ENDING" in error_str
                or "EGRESS_LIMIT_REACHED" in error_str
            ):
                logger.info(
                    f"LiveKit egress {egress_id} already completed/ending/limit reached, continuing: {error_str}"
                )
            else:
                error_msg = f"Failed to stop LiveKit egress {egress_id}: {error_str}"
                logger.exception(error_msg)
                errors.append(error_msg)

        try:
            # Step 2: Signal Mux stream complete
            logger.info(f"Signaling Mux stream complete: {mux_stream_id}")
            self.mux.signal_live_stream_complete(mux_stream_id)
            logger.info(f"Successfully signaled Mux stream complete: {mux_stream_id}")

        except Exception as e:
            error_msg = f"Failed to signal Mux stream complete {mux_stream_id}: {e!s}"
            logger.exception(error_msg)
            errors.append(error_msg)

        # Determine target state based on current state
        # - LIVE -> ENDING (stream was active, will transition to STOPPED via webhook)
        # - ENDING -> ABORTED -> STOPPED (stream was ending, force to terminal)
        # - Other states -> ABORTED -> CANCELLED (stream never went live)
        try:
            if session.status == SessionState.LIVE:
                await self.update_session_state(session, SessionState.ENDING)
                logger.info(
                    f"Session {session.room_id} state updated to ENDING after ending live stream"
                )

                # Schedule delayed cleanup to check Mux status and finalize session
                # This will wait 1 minute, then check if Mux stream is still active.
                # If not active, it will transition to STOPPED and notify External Live.
                schedule_delayed_cleanup(
                    session_id=session.session_id,
                    mux_stream_id=mux_stream_id,
                )
            else:
                # For PUBLISHING, ENDING, or other states, transition through ABORTED
                await self.update_session_state(session, SessionState.ABORTED)
                logger.info(f"Session {session.room_id} state updated to ABORTED")

                # Determine final state: STOPPED for ENDING, CANCELLED for others
                if session.status == SessionState.ENDING:
                    final_state = SessionState.STOPPED
                else:
                    final_state = SessionState.CANCELLED

                # Refresh session and transition to final state
                updated_session = await Session.find_one(Session.session_id == session.session_id)
                if updated_session:
                    await self.update_session_state(updated_session, final_state)
                    logger.info(f"Session {session.room_id} state updated to {final_state}")

        except Exception as e:
            error_msg = f"Failed to update session {room_name} state: {e!s}"
            logger.exception(error_msg)
            errors.append(error_msg)

        # If there were any errors, raise them
        if errors:
            raise AppError(
                errcode=AppErrorCode.E_INTERNAL_ERROR,
                errmesg=f"Live stream ended with errors: {'; '.join(errors)}",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            )

        logger.info(f"Live stream ended successfully for room={room_name}")
