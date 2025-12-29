from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from loguru import logger

from app.api.flc.dependency import CurrentUser
from app.api.flc.schemas.base import CwOut
from app.api.flc.schemas.session_egress import UpdateRoomMetadataIn, UpdateRoomMetadataOut
from app.api.flc.schemas.session_ingress import (
    AccessTokenOut,
    CreateRoomIn,
    CreateRoomOut,
    DeleteRoomIn,
    DeleteRoomOut,
    GetGuestTokenIn,
    GetHostTokenIn,
    GetInviteLinkOut,
    GetRecorderTokenIn,
    UpdateParticipantNameIn,
    UpdateParticipantNameOut,
)
from app.app_config import get_app_environ_config
from app.domain.live.session.session_domain import SessionService
from app.domain.live.session.session_models import SessionUpdateParams
from app.domain.live.session.session_state_machine import SessionStateMachine
from app.schemas.session_state import SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

router = APIRouter(prefix="/flc/session/ingress")

# Singleton instance
_session_service = SessionService()


def get_session_service() -> SessionService:
    """Get the singleton SessionService instance."""
    return _session_service


@router.post("/create_room")
async def create_room(
    room_data: CreateRoomIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[CreateRoomOut]:
    """Create a LiveKit room for a session.

    This endpoint creates a LiveKit room that can be used for real-time
    communication. Typically called after creating a session to prepare
    the room for participants.

    This endpoint is idempotent: if the session is already in READY state,
    it returns the existing room info without error.
    """
    # Resolve session_id from either session_id or room_id
    if room_data.session_id:
        session = await service.get_session(session_id=room_data.session_id)
    else:
        # room_id is guaranteed to exist by validator
        assert room_data.room_id is not None
        session = await service.get_active_session_by_room_id(room_id=room_data.room_id)

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to create room for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Check if session can transition to READY (terminal states cannot)
    # Allow if already READY (idempotent) or can transition to READY
    if session.status != SessionState.READY and not SessionStateMachine.can_transition(
        session.status, SessionState.READY
    ):
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_TERMINATED,
            errmesg=f"Cannot create room for terminated session (status: {session.status}). Please create a new session.",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    if session.status == SessionState.READY:
        logger.info(
            f"Session {session.room_id} already in READY state, returning existing room info"
        )

    # Use env var limit as the effective max_participants
    cfg = get_app_environ_config()
    effective_max_participants = min(room_data.max_participants, cfg.MAX_PARTICIPANTS_LIMIT)

    # Create or get existing room (LiveKit create_room is idempotent)
    room = await service.create_room(
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        metadata=room_data.metadata,
        empty_timeout=room_data.empty_timeout,
        max_participants=effective_max_participants,
    )

    # Only transition state if not already in READY (idempotent behavior)
    if session.status != SessionState.READY:
        await service.update_session_state(
            session_id=session.session_id,
            new_state=SessionState.READY,
        )

    # Store max_participants in session for frontend access
    await service.update_session(
        session_id=session.session_id,
        params=SessionUpdateParams(max_participants=effective_max_participants),
    )

    return CwOut[CreateRoomOut](
        results=CreateRoomOut(
            room_name=room.name,
            room_sid=room.sid,
            metadata=room.metadata,
            max_participants=effective_max_participants,
        )
    )


@router.post("/delete_room")
async def delete_room(
    room_data: DeleteRoomIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[DeleteRoomOut]:
    """Delete a LiveKit room.

    This endpoint deletes a LiveKit room. Typically called after a session
    has reached a terminal state (STOPPED, CANCELLED, ABORTED) to clean up
    resources.

    This is the counterpart to create_room.
    """
    # Resolve session from either session_id or room_id
    if room_data.session_id:
        session = await service.get_session(session_id=room_data.session_id)
    else:
        # room_id is guaranteed to exist by validator
        assert room_data.room_id is not None
        session = await service.get_last_session_by_room_id(room_id=room_data.room_id)

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to delete room for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Delete the LiveKit room
    await service.delete_room(room_name=session.room_id)

    return CwOut[DeleteRoomOut](
        results=DeleteRoomOut(
            room_name=session.room_id,
            deleted=True,
        )
    )


@router.post("/get_host_token")
async def get_host_token(
    token_request: GetHostTokenIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[AccessTokenOut]:
    """Generate a LiveKit access token for a host.

    Host tokens grant full permissions including:
    - Publishing audio/video tracks
    - Screen sharing
    - Recording
    - Room administration
    """
    # Resolve session_id from either session_id or room_id
    if token_request.session_id:
        session = await service.get_session(session_id=token_request.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=token_request.room_id)  # type: ignore

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to generate host token for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    token = await service.get_host_access_token(
        identity=user.user_id,
        room_name=session.room_id,
        display_name=user.user_id,
        metadata=token_request.metadata,
    )

    now = datetime.now(timezone.utc)
    token_ttl = 3600  # 1 hour default

    # Get LiveKit URL from config
    cfg = get_app_environ_config()
    livekit_url = cfg.LIVEKIT_URL
    if not livekit_url:
        raise FlcError(
            errcode=FlcErrorCode.E_LIVEKIT_NOT_CONFIGURED,
            errmesg="LIVEKIT_URL is not configured",
            status_code=FlcStatusCode.INTERNAL_SERVER_ERROR,
        )

    return CwOut[AccessTokenOut](
        results=AccessTokenOut(
            token=token,
            token_ttl=token_ttl,
            token_issued_at=now,
            token_expires_at=datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc),
            identity=user.user_id,
            room_name=session.room_id,  # Return room_id as room_name
            livekit_url=livekit_url,
        )
    )


@router.post("/get_guest_token")
async def get_guest_token(
    token_request: GetGuestTokenIn,
    service: SessionService = Depends(get_session_service),
) -> CwOut[AccessTokenOut]:
    """Generate a LiveKit access token for a guest/viewer.

    Guest tokens grant limited permissions based on the can_publish flag.
    - If can_publish=True: Can publish audio/video tracks
    - If can_publish=False: View-only access
    """
    # Resolve session_id from either session_id or room_id
    if token_request.session_id:
        session = await service.get_session(session_id=token_request.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=token_request.room_id)  # type: ignore

    # Generate a unique identity for the guest
    import uuid

    identity = f"guest_{uuid.uuid4().hex[:12]}"

    token = await service.get_guest_access_token(
        identity=identity,
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        display_name=token_request.display_name,
        metadata=token_request.metadata,
        can_publish=token_request.can_publish,
    )

    now = datetime.now(timezone.utc)
    token_ttl = 3600  # 1 hour default

    # Get LiveKit URL from config
    cfg = get_app_environ_config()
    livekit_url = cfg.LIVEKIT_URL
    if not livekit_url:
        raise FlcError(
            errcode=FlcErrorCode.E_LIVEKIT_NOT_CONFIGURED,
            errmesg="LIVEKIT_URL is not configured",
            status_code=FlcStatusCode.INTERNAL_SERVER_ERROR,
        )

    return CwOut[AccessTokenOut](
        results=AccessTokenOut(
            token=token,
            token_ttl=token_ttl,
            token_issued_at=now,
            token_expires_at=datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc),
            identity=identity,
            room_name=session.room_id,  # Return room_id as room_name
            livekit_url=livekit_url,
        )
    )


@router.post("/get_recorder_token", tags=["Dev Only"])
async def get_recorder_token(
    token_request: GetRecorderTokenIn,
    service: SessionService = Depends(get_session_service),
) -> CwOut[AccessTokenOut]:
    """Generate a LiveKit access token for a recorder to join and record the live.

    Recorder tokens grant limited permissions:
    - Can join the room
    - Can subscribe to all tracks (receive audio/video)
    - Cannot publish any tracks
    - No admin privileges

    This endpoint does not require authentication - it's intended for
    recording services that need to join rooms.
    """
    session = await service.get_last_session_by_room_id(room_id=token_request.room_id)

    identity = token_request.identity or f"recorder-{token_request.room_id}"
    token = await service.get_recorder_access_token(
        room_name=session.room_id,
        identity=identity,
        display_name=token_request.display_name,
        metadata=token_request.metadata,
    )

    now = datetime.now(timezone.utc)
    token_ttl = 3600  # 1 hour default

    # Get LiveKit URL from config
    cfg = get_app_environ_config()
    livekit_url = cfg.LIVEKIT_URL
    if not livekit_url:
        raise FlcError(
            errcode=FlcErrorCode.E_LIVEKIT_NOT_CONFIGURED,
            errmesg="LIVEKIT_URL is not configured",
            status_code=FlcStatusCode.INTERNAL_SERVER_ERROR,
        )

    return CwOut[AccessTokenOut](
        results=AccessTokenOut(
            token=token,
            token_ttl=token_ttl,
            token_issued_at=now,
            token_expires_at=datetime.fromtimestamp(now.timestamp() + token_ttl, tz=timezone.utc),
            identity=identity,
            room_name=session.room_id,
            livekit_url=livekit_url,
        )
    )


@router.post("/update_room_metadata")
async def update_room_metadata(
    metadata_data: UpdateRoomMetadataIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[UpdateRoomMetadataOut]:
    """Update room metadata for a session.

    Room metadata is shared application-specific state that is visible to all
    participants in the room. This can be used to control shared state like
    layout mode, theme settings, or other configuration.

    The metadata must be a JSON string and is limited to 64 KiB in size.

    All participants in the room will receive a RoomMetadataChanged event
    when the metadata is updated.

    This endpoint requires the user to own the session.

    Reference:
        https://docs.livekit.io/home/client/state/room-metadata/
    """
    # Resolve session_id from either session_id or room_id
    if metadata_data.session_id:
        session = await service.get_session(session_id=metadata_data.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_last_session_by_room_id(room_id=metadata_data.room_id)  # type: ignore

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to update room metadata for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Update room metadata
    room_info = await service.update_room_metadata(
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        metadata=metadata_data.metadata,
    )

    return CwOut[UpdateRoomMetadataOut](
        results=UpdateRoomMetadataOut(
            room=room_info.name,
            sid=room_info.sid,
            metadata=room_info.metadata,
        )
    )


@router.post("/update_participant_name")
async def update_participant_name(
    update_data: UpdateParticipantNameIn,
    service: SessionService = Depends(get_session_service),
) -> CwOut[UpdateParticipantNameOut]:
    """Update a participant's display name.

    This endpoint allows guests to change their display name while in a session.
    The participant must be the one making the request.

    All participants in the room will receive a ParticipantNameChanged event
    when the name is updated.

    Reference:
        https://docs.livekit.io/home/server/managing-participants/#updateparticipant
    """
    # Resolve session_id from either session_id or room_id
    if update_data.session_id:
        session = await service.get_session(session_id=update_data.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_last_session_by_room_id(room_id=update_data.room_id)  # type: ignore

    # Update participant name
    participant = await service.update_participant(
        room_name=session.room_id,  # Use room_id as room_name for LiveKit
        identity=update_data.identity,
        name=update_data.name,
    )

    return CwOut[UpdateParticipantNameOut](
        results=UpdateParticipantNameOut(
            identity=participant.identity,
            name=participant.name,
            sid=participant.sid,
        )
    )


@router.get("/get_invite_link")
async def get_invite_link(
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
    session_id: str | None = None,
    room_id: str | None = None,
) -> CwOut[GetInviteLinkOut]:
    """Get invite link for a session.

    Returns the invite link that can be shared with guests to join the session.
    Format: {FRONTEND_INVITE_LINK_BASE_URL}{FRONTEND_BASE_PATH}{FRONTEND_JOIN_PATH}/{room_id}?host={user_id}
    """
    if not session_id and not room_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="Either session_id or room_id must be provided",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    # Resolve session_id from either session_id or room_id
    if session_id:
        session = await service.get_session(session_id=session_id)
    else:
        session = await service.get_active_session_by_room_id(room_id=room_id)  # type: ignore

    if session.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to get invite link for this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    cfg = get_app_environ_config()

    if not cfg.FRONTEND_INVITE_LINK_BASE_URL:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="FRONTEND_INVITE_LINK_BASE_URL is not configured",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    base_url = cfg.FRONTEND_INVITE_LINK_BASE_URL.strip().rstrip("/")
    base_path = cfg.FRONTEND_BASE_PATH.strip()
    join_path = cfg.FRONTEND_JOIN_PATH.strip().lstrip("/")

    invite_link = f"{base_url}{base_path}/{join_path}/{session.room_id}?host={session.user_id}"

    return CwOut[GetInviteLinkOut](results=GetInviteLinkOut(invite_link=invite_link))
