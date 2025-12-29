from fastapi import APIRouter, Depends, Request

from app.api.flc.dependency import CurrentUser
from app.api.flc.schemas.base import CwOut
from app.api.flc.schemas.session_egress import (
    ClientPlatform,
    EndLiveStreamIn,
    EndLiveStreamOut,
    StartLiveStreamIn,
    StartLiveStreamOut,
)
from app.domain.live.session.session_domain import SessionService
from app.schemas.session_state import SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

router = APIRouter(prefix="/flc/session/egress")

# Singleton instance
_session_service = SessionService()


def get_session_service() -> SessionService:
    """Get the singleton SessionService instance."""
    return _session_service


@router.post("/start_live_stream")
async def start_live_stream(
    request: Request,
    stream_data: StartLiveStreamIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[StartLiveStreamOut]:
    """Start live streaming for a session.

    This endpoint:
    1. Creates a Mux livestream to get RTMP endpoint
    2. Starts LiveKit room composite egress to stream to Mux
    3. Updates session state to LIVE
    4. Returns egress info and Mux stream data with playback URLs

    The host must have joined the room (session in PUBLISHING state) before
    calling this endpoint.
    """
    # Resolve session_id from either session_id or room_id
    if stream_data.session_id:
        session = await service.get_session(session_id=stream_data.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=stream_data.room_id)  # type: ignore

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to start live stream for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Start the live stream (idempotent - returns existing data if already in progress)
    # Get referer header as fallback for FRONTEND_BASE_URL
    referer = request.headers.get("referer") or request.headers.get("origin")
    result = await service.start_live(
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        layout=stream_data.layout,
        referer=referer,
        base_path=stream_data.base_path,
        width=stream_data.width,
        height=stream_data.height,
        is_mobile=stream_data.platform == ClientPlatform.MOBILE,
    )

    return CwOut[StartLiveStreamOut](
        results=StartLiveStreamOut(
            egress_id=result.egress_id,
            mux_stream_id=result.mux_stream_id,
            mux_stream_key=result.mux_stream_key,
            mux_rtmp_url=result.mux_rtmp_url,
            mux_playback_ids=result.mux_playback_ids,
        )
    )


@router.post("/end_live_stream")
async def end_live_stream(
    stream_data: EndLiveStreamIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[EndLiveStreamOut]:
    """End live streaming for a session.

    This endpoint:
    1. Stops the LiveKit egress
    2. Signals Mux that the livestream is complete
    3. Updates session state to ENDING

    The session must be in LIVE state before calling this endpoint.
    """
    # Resolve session_id from either session_id or room_id
    # If session not found, the stream has already ended - return success
    try:  # noqa: FLC002
        if stream_data.session_id:
            session = await service.get_session(session_id=stream_data.session_id)
        else:
            # room_id is guaranteed to exist by validator
            session = await service.get_active_session_by_room_id(room_id=stream_data.room_id)  # type: ignore
    except FlcError as e:
        if e.errcode == FlcErrorCode.E_SESSION_NOT_FOUND:
            # Session not found means stream already ended - return success
            return CwOut[EndLiveStreamOut](
                results=EndLiveStreamOut(
                    message="Live stream already ended",
                    session_id=stream_data.session_id or "",
                )
            )
        raise

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to end live stream for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Check if session is already in a terminal state - return success (idempotent)
    terminal_states = {SessionState.STOPPED, SessionState.CANCELLED}
    if session.status in terminal_states:
        return CwOut[EndLiveStreamOut](
            results=EndLiveStreamOut(
                message="Live stream already ended",
                session_id=session.session_id,
            )
        )

    # Read egress_id and mux_stream_id from session config (trusted source)
    config = session.runtime

    stored_egress_id = config.livekit.egress_id if config.livekit else None
    stored_mux_stream_id = config.mux.mux_stream_id if config.mux else None

    # Validate that the session has active egress info
    # If no egress info but session not terminal, stream was never started or already cleaned up
    if not stored_egress_id or not stored_mux_stream_id:
        return CwOut[EndLiveStreamOut](
            results=EndLiveStreamOut(
                message="Live stream already ended",
                session_id=session.session_id,
            )
        )

    # Validate that provided IDs match stored IDs (prevent cross-session attacks)
    if stream_data.egress_id != stored_egress_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="egress_id does not match the session's active egress",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    if stream_data.mux_stream_id != stored_mux_stream_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="mux_stream_id does not match the session's active stream",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    # End the live stream using validated IDs from session config
    await service.end_live(
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        egress_id=stored_egress_id,
        mux_stream_id=stored_mux_stream_id,
    )

    return CwOut[EndLiveStreamOut](
        results=EndLiveStreamOut(
            message="Live stream ended successfully",
            session_id=session.session_id,
        )
    )
