"""Caption ingress endpoints for enabling/disabling captions."""

from typing import Annotated

from fastapi import APIRouter, Depends
from streaq import Worker

from app.api.v1.dependency import CurrentUser
from app.api.v1.schemas.base import ApiOut
from app.api.v1.schemas.session_ingress import (
    CaptionStatusRequest,
    CaptionStatusResponse,
    DisableCaptionRequest,
    DisableCaptionResponse,
    EnableCaptionRequest,
    EnableCaptionResponse,
    UpdateParticipantLanguageRequest,
    UpdateParticipantLanguageResponse,
)
from app.shared.storage.redis import get_redis_client
from app.domain.live.session.session_domain import SessionService
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode
from app.workers.caption_agent_worker import (
    CaptionAgentParams,
    start_caption_agent,
    stop_caption_agent,
)
from app.workers.caption_agent_worker import worker as caption_worker

router = APIRouter(prefix="/session/ingress", tags=["Next Phase"])

# Singleton instance
_session_service = SessionService()


def get_session_service() -> SessionService:
    """Get the singleton SessionService instance."""
    return _session_service


def get_caption_worker() -> Worker:
    """Dependency to get the caption agent worker for enqueueing."""
    return caption_worker


@router.post("/enable_caption", response_model=ApiOut[EnableCaptionResponse])
async def enable_caption(
    params: EnableCaptionRequest,
    w: Annotated[Worker, Depends(get_caption_worker)],
    service: SessionService = Depends(get_session_service),
) -> ApiOut[EnableCaptionResponse]:
    """Enable caption for a live session.

    This endpoint triggers a LiveKit agent to join the room and start
    listening to audio and transcribing via STT (Speech-to-Text).

    The agent will publish caption data back to the room that clients
    can subscribe to.
    """
    # Resolve session_id from either session_id or room_id
    if params.session_id:
        session = await service.get_session(session_id=params.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=params.room_id)  # type: ignore

    # Queue the agent start task
    agent_params = CaptionAgentParams(
        session_id=session.session_id,
        translation_languages=params.translation_languages,
    )

    async with w:
        task = await start_caption_agent.enqueue(agent_params.model_dump())

    return ApiOut[EnableCaptionResponse](
        results=EnableCaptionResponse(
            session_id=session.session_id,
            status="starting",
            job_id=task.id if task else None,
        )
    )


@router.post("/disable_caption", response_model=ApiOut[DisableCaptionResponse])
async def disable_caption(
    params: DisableCaptionRequest,
    user: CurrentUser,
    w: Annotated[Worker, Depends(get_caption_worker)],
    service: SessionService = Depends(get_session_service),
) -> ApiOut[DisableCaptionResponse]:
    """Disable caption/interpretation for a live session.

    This stops the LiveKit agent from processing audio and publishing captions.
    """
    # Resolve session_id from either session_id or room_id
    if params.session_id:
        session = await service.get_session(session_id=params.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=params.room_id)  # type: ignore

    if session.user_id != user.user_id:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_FORBIDDEN,
            errmesg="You don't have permission to disable captions for this session",
            status_code=HttpStatusCode.FORBIDDEN,
        )

    # Queue the agent stop task
    async with w:
        task = await stop_caption_agent.enqueue(session.session_id)

    return ApiOut[DisableCaptionResponse](
        results=DisableCaptionResponse(
            session_id=session.session_id,
            status="stopping",
            job_id=task.id if task else None,
        )
    )


@router.post("/get_caption_status", response_model=ApiOut[CaptionStatusResponse])
async def get_caption_status(
    params: CaptionStatusRequest,
    user: CurrentUser,
    service: SessionService = Depends(get_session_service),
) -> ApiOut[CaptionStatusResponse]:
    """Get the current caption/interpretation status for a session."""
    from app.shared.config import custom_config

    # Resolve session_id from either session_id or room_id
    if params.session_id:
        session = await service.get_session(session_id=params.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=params.room_id)  # type: ignore

    # Check caption agent state in Redis
    redis_major_label = custom_config.get_redis_major_label()
    redis = get_redis_client(redis_major_label)
    agent_key = f"caption-agent:{session.session_id}"
    agent_data = await redis.hgetall(agent_key)  # type: ignore[misc]

    if not agent_data:
        # No agent running
        return ApiOut[CaptionStatusResponse](
            results=CaptionStatusResponse(
                session_id=session.session_id,
                enabled=False,
                status="not_running",
            )
        )

    # Agent exists, return status
    return ApiOut[CaptionStatusResponse](
        results=CaptionStatusResponse(
            session_id=session.session_id,
            enabled=True,
            status=agent_data.get(b"status", b"unknown").decode("utf-8"),
        )
    )


# Attribute key for storing STT language preference
STT_LANGUAGE_ATTRIBUTE = "stt_language"


@router.post("/update-language", response_model=ApiOut[UpdateParticipantLanguageResponse])
async def update_participant_language(
    params: UpdateParticipantLanguageRequest,
    service: SessionService = Depends(get_session_service),
) -> ApiOut[UpdateParticipantLanguageResponse]:
    """Update a participant's original language for STT processing.

    This endpoint allows a participant to change their spoken language while
    the caption agent is running. The agent will detect the attribute change
    and restart STT for this participant with the new language configuration.

    Other participants' caption functionality is not affected.

    The language update is propagated via LiveKit participant attributes,
    which the MultiSpeakerCaptionManager listens for to dynamically update
    the STT configuration.
    """
    from app.services.integrations.livekit_service import livekit_service

    # Resolve session_id from either session_id or room_id
    if params.session_id:
        session = await service.get_session(session_id=params.session_id)
    else:
        # room_id is guaranteed to exist by validator
        session = await service.get_active_session_by_room_id(room_id=params.room_id)  # type: ignore

    # Update participant attributes with new language
    await livekit_service.update_participant(
        room=session.room_id,
        identity=params.participant_identity,
        attributes={STT_LANGUAGE_ATTRIBUTE: params.language},
    )

    return ApiOut[UpdateParticipantLanguageResponse](
        results=UpdateParticipantLanguageResponse(
            session_id=session.session_id,
            participant_identity=params.participant_identity,
            language=params.language,
            status="updated",
        )
    )
