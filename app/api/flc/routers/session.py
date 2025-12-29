from fastapi import APIRouter, Depends, Query

from app.api.flc.dependency import CurrentUser
from app.api.flc.schemas.base import CwOut
from app.api.flc.schemas.session import (
    CreateSessionIn,
    CreateSessionOut,
    EndSessionOut,
    ListSessionsOut,
    SessionOut,
    UpdateSessionIn,
)
from app.domain.live.session.session_domain import SessionService
from app.domain.live.session.session_models import SessionCreateParams, SessionUpdateParams
from app.schemas import SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

router = APIRouter(prefix="/flc/session")

# Singleton instance
_session_service = SessionService()


def get_session_service() -> SessionService:
    """Get the singleton SessionService instance."""
    return _session_service


@router.post("/create_session")
async def create_session(
    session: CreateSessionIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[CreateSessionOut]:
    """Create a new session for the authenticated user."""
    params = SessionCreateParams(
        channel_id=session.channel_id,
        user_id=user.user_id,
        title=session.title,
        location=session.location,
        description=session.description,
        cover=session.cover,
        lang=session.lang,
        category_ids=session.category_ids,
        end_existing=session.end_existing,
    )

    result = await service.create_session(params)

    return CwOut[CreateSessionOut](
        results=CreateSessionOut(
            session_id=result.session_id,
            room_id=result.room_id,
        )
    )


@router.get("/list_sessions")
async def list_sessions(
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
    cursor: str | None = Query(None, description="Pagination cursor"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
    channel_id: str | None = Query(None, description="Filter by channel ID"),
    status: list[SessionState] | None = Query(None, description="Filter by session status(es)"),
) -> CwOut[ListSessionsOut]:
    """List sessions for the authenticated user."""

    result = await service.list_sessions(
        cursor=cursor,
        page_size=page_size,
        channel_id=channel_id,
        user_id=user.user_id,
        status=status,
    )

    sessions_out = [
        SessionOut(
            session_id=sess.session_id,
            room_id=sess.room_id,
            channel_id=sess.channel_id,
            title=sess.title,
            location=sess.location,
            description=sess.description,
            cover=sess.cover,
            lang=sess.lang,
            category_ids=sess.category_ids,
            status=sess.status.value,
            max_participants=sess.max_participants,
            runtime=sess.runtime,
            post_id=sess.runtime.post_id,
            created_at=sess.created_at,
            started_at=sess.started_at,
            stopped_at=sess.stopped_at,
        )
        for sess in result.sessions
    ]

    return CwOut[ListSessionsOut](
        results=ListSessionsOut(
            sessions=sessions_out,
            next_cursor=result.next_cursor,
        )
    )


@router.get("/get_session")
async def get_session(
    session_id: str | None = Query(None, description="Session ID to retrieve"),
    room_id: str | None = Query(
        None,
        description="Room ID to retrieve. When querying with room_id, tries to find an active session or returns not found.",
    ),
    service: SessionService = Depends(get_session_service),
) -> CwOut[SessionOut]:
    """Get a specific session by session_id or room_id."""
    if not session_id and not room_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="Either session_id or room_id must be provided",
            status_code=FlcStatusCode.BAD_REQUEST,
        )
    if session_id and room_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="Only one of session_id or room_id can be provided",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    # Resolve session from either session_id or room_id
    if session_id:
        result = await service.get_session(session_id=session_id)
    else:
        result = await service.get_active_session_by_room_id(room_id=room_id)  # type: ignore

    return CwOut[SessionOut](
        results=SessionOut(
            session_id=result.session_id,
            room_id=result.room_id,
            channel_id=result.channel_id,
            title=result.title,
            location=result.location,
            description=result.description,
            cover=result.cover,
            lang=result.lang,
            category_ids=result.category_ids,
            status=result.status.value,
            max_participants=result.max_participants,
            runtime=result.runtime,
            post_id=result.runtime.post_id,
            created_at=result.created_at,
            started_at=result.started_at,
            stopped_at=result.stopped_at,
        )
    )


@router.get("/get_active_session")
async def get_active_session(
    user: CurrentUser,
    channel_id: str = Query(..., description="Channel ID to get active session for"),
    service: SessionService = Depends(get_session_service),
) -> CwOut[SessionOut]:
    """Get the active session for a channel.

    Returns the currently active session (IDLE, READY, PUBLISHING, LIVE, or ENDING)
    for the specified channel.
    """
    result = await service.get_active_session_by_channel(channel_id=channel_id)

    # Verify user owns this session
    if result.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to access this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    return CwOut[SessionOut](
        results=SessionOut(
            session_id=result.session_id,
            room_id=result.room_id,
            channel_id=result.channel_id,
            title=result.title,
            location=result.location,
            description=result.description,
            cover=result.cover,
            lang=result.lang,
            category_ids=result.category_ids,
            status=result.status.value,
            max_participants=result.max_participants,
            runtime=result.runtime,
            post_id=result.runtime.post_id,
            created_at=result.created_at,
            started_at=result.started_at,
            stopped_at=result.stopped_at,
        )
    )


@router.post("/update_session")
async def update_session(
    session: UpdateSessionIn,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> CwOut[SessionOut]:
    """Update a session owned by the authenticated user."""
    # Resolve session_id from either session_id or room_id
    if session.session_id:
        existing = await service.get_session(session_id=session.session_id)
    else:
        # room_id is guaranteed to exist by validator
        existing = await service.get_active_session_by_room_id(room_id=session.room_id)  # type: ignore

    if existing.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to update this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # Only include fields that were explicitly provided in the request
    update_data = session.model_dump(
        exclude_unset=True,
        include={"title", "location", "description", "cover", "lang", "category_ids"},
    )
    params = SessionUpdateParams(**update_data)

    result = await service.update_session(
        session_id=existing.session_id,
        params=params,
    )

    return CwOut[SessionOut](
        results=SessionOut(
            session_id=result.session_id,
            room_id=result.room_id,
            channel_id=result.channel_id,
            title=result.title,
            location=result.location,
            description=result.description,
            cover=result.cover,
            lang=result.lang,
            category_ids=result.category_ids,
            status=result.status.value,
            max_participants=result.max_participants,
            runtime=result.runtime,
            post_id=result.runtime.post_id,
            created_at=result.created_at,
            started_at=result.started_at,
            stopped_at=result.stopped_at,
        )
    )


@router.post("/end_session")
async def end_session(
    user: CurrentUser,
    session_id: str | None = Query(None, description="Session ID to end"),
    room_id: str | None = Query(None, description="Room ID to end"),
    service: SessionService = Depends(get_session_service),
) -> CwOut[EndSessionOut]:
    """End a session - stops egress, deletes room, and updates state to STOPPED.

    This performs a complete session teardown:
    1. Stops LiveKit egress (if active)
    2. Completes Mux stream (if active)
    3. Deletes LiveKit room
    4. Updates session state to STOPPED
    """
    if not session_id and not room_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="Either session_id or room_id must be provided",
            status_code=FlcStatusCode.BAD_REQUEST,
        )
    if session_id and room_id:
        raise FlcError(
            errcode=FlcErrorCode.E_INVALID_REQUEST,
            errmesg="Only one of session_id or room_id can be provided",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

    # Resolve session from either session_id or room_id
    if session_id:
        existing = await service.get_session(session_id=session_id)
    else:
        existing = await service.get_active_session_by_room_id(room_id=room_id)  # type: ignore

    if existing.user_id != user.user_id:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_FORBIDDEN,
            errmesg="Not authorized to end this session",
            status_code=FlcStatusCode.FORBIDDEN,
        )

    # End the session using the resolved session_id
    result = await service.end_session(session_id=existing.session_id)

    return CwOut[EndSessionOut](
        results=EndSessionOut(
            session_id=result.session_id,
            room_id=result.room_id,
            status=result.status.value,
        )
    )
