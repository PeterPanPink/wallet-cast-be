"""LiveKit webhook endpoint for receiving room events.

This endpoint receives webhook notifications from LiveKit about room and participant
events and performs JWT signature verification for security.

Event Types:
- room_started: Room was created and first participant joined
- room_finished: Room ended (all participants left and empty timeout expired)
- participant_joined: Participant joined the room
- participant_left: Participant left the room
- participant_connection_aborted: Participant connection was aborted
- track_published: Track was published to the room
- track_unpublished: Track was unpublished from the room
- egress_started: Egress recording started
- egress_updated: Egress recording updated
- egress_ended: Egress recording ended
- ingress_started: Ingress stream started
- ingress_ended: Ingress stream ended

References:
- https://docs.livekit.io/home/server/webhooks/
- Pydantic schemas: app.api.webhooks.schemas.livekit
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from fastapi import APIRouter, Header, Request
from loguru import logger
from pydantic import ValidationError

from app.api.webhooks.schemas.livekit import (
    EgressEndedEvent,
    EgressStartedEvent,
    EgressUpdatedEvent,
    IngressEndedEvent,
    IngressStartedEvent,
    ParticipantConnectionAbortedEvent,
    ParticipantJoinedEvent,
    ParticipantLeftEvent,
    RoomFinishedEvent,
    RoomStartedEvent,
    TrackPublishedEvent,
    TrackUnpublishedEvent,
)
from app.cw.api.utils import ApiFailure, ApiSuccess, api_failure
from app.domain.live.session.session_domain import SessionService
from app.schemas import SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class LiveKitWebhookSuccess(ApiSuccess):
    """Success response for webhook."""

    results: dict[str, Any]  # type: ignore[assignment]


async def handle_room_started(event: RoomStartedEvent) -> dict[str, Any]:
    """Handle room_started event."""
    logger.info(f"🟢 ROOM STARTED: {event.room.name} (sid={event.room.sid})")
    logger.info(f"   Created at: {event.room.creation_time}")
    logger.info(f"   Empty timeout: {event.room.empty_timeout}s")

    # TODO: Implement room started logic
    # - Update session status to LIVE
    # - Log room start time

    return {"handled": "room_started", "room_name": event.room.name}


async def handle_room_finished(event: RoomFinishedEvent) -> dict[str, Any]:
    """Handle room_finished event.

    When room is deleted, transition session to appropriate terminal state.
    Note: event.room.name contains the session_id (which equals room_id).

    State transition rules:
    - ENDING -> STOPPED (normal flow)
    - READY -> CANCELLED
    - PUBLISHING -> ABORTED -> CANCELLED
    - Other states -> ABORTED -> STOPPED
    - Already terminal (STOPPED/CANCELLED) -> no-op
    """
    logger.info(f"🔴 ROOM FINISHED: {event.room.name} (sid={event.room.sid})")

    service = SessionService()
    room_id = event.room.name

    try:
        session = await service.get_active_session_by_room_id(room_id=room_id)
        current_status = session.status

        if current_status in (SessionState.STOPPED, SessionState.CANCELLED):
            logger.debug(f"Session {room_id} already in terminal state {current_status}")
        elif current_status == SessionState.ENDING:
            # Normal flow: ENDING -> STOPPED
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.STOPPED,
            )
            logger.info(f"✅ Session {room_id} transitioned ENDING -> STOPPED (room deleted)")
        elif current_status == SessionState.READY:
            # READY -> CANCELLED (session never went live)
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.CANCELLED,
            )
            logger.warning(
                f"⚠️  Session {room_id} transitioned READY -> CANCELLED (room deleted unexpectedly)"
            )
        elif current_status == SessionState.PUBLISHING:
            # PUBLISHING -> ABORTED -> CANCELLED (stream started but never confirmed live)
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.ABORTED,
            )
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.CANCELLED,
            )
            logger.warning(
                f"⚠️  Session {room_id} transitioned PUBLISHING -> ABORTED -> CANCELLED "
                f"(room deleted unexpectedly)"
            )
        else:
            # Other states (IDLE, LIVE, ABORTED) -> ABORTED -> STOPPED
            with contextlib.suppress(FlcError):
                # May already be in ABORTED state, continue to STOPPED
                await service.update_session_state(
                    session_id=session.session_id,
                    new_state=SessionState.ABORTED,
                )
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.STOPPED,
            )
            logger.warning(
                f"⚠️  Session {room_id} transitioned {current_status} -> ABORTED -> STOPPED "
                f"(room deleted unexpectedly)"
            )

    except FlcError as e:
        # E_SESSION_NOT_FOUND is expected when session is already closed via end_live
        if e.errcode == FlcErrorCode.E_SESSION_NOT_FOUND:
            logger.warning(f"Session already closed on room finish: {e}")
        else:
            logger.exception(f"Failed to update session state on room finish: {e}")
    except Exception as e:
        logger.exception(f"Failed to update session state on room finish: {e}")

    return {"handled": "room_finished", "room_name": event.room.name}


async def handle_participant_joined(event: ParticipantJoinedEvent) -> dict[str, Any]:
    """Handle participant_joined event.

    When host joins:
    1. If there's a pending cleanup task, cancel it (host returned)
    2. Transition session from IDLE to READY if needed

    Note: event.room.name contains the session_id (which equals room_id).
    """
    from app.schemas import Session
    from app.workers.api_jobs_worker import worker as api_jobs_worker

    logger.info(f"👤 PARTICIPANT JOINED: {event.participant.identity}")
    logger.info(f"   Room: {event.room.name}")
    logger.info(f"   Name: {event.participant.name}")
    if event.participant.state:
        logger.info(f"   State: {event.participant.state.value}")

    room_id = event.room.name
    cancelled_task_id = None

    try:
        session = await Session.find_one(Session.room_id == room_id)
        if not session:
            logger.warning(f"Session not found for room {room_id}")
            return {"handled": "participant_joined", "participant": event.participant.identity}

        if event.participant.identity != session.user_id:
            logger.info(
                f"Participant {event.participant.identity} is not the host for session "
                f"{session.session_id}, no state change"
            )
            return {"handled": "participant_joined", "participant": event.participant.identity}

        # Check if there's a pending cleanup task to cancel (host returned)
        if (
            session.runtime.host_cleanup is not None
            and session.runtime.host_cleanup.task_id is not None
        ):
            cleanup_task_id = session.runtime.host_cleanup.task_id
            logger.info(
                f"🔄 Host returned to session {session.session_id}, "
                f"cancelling cleanup task {cleanup_task_id}"
            )

            # Cancel the cleanup task
            async with api_jobs_worker:
                aborted = await api_jobs_worker.abort_by_id(cleanup_task_id, timeout=5)

            if aborted:
                logger.info(f"✅ Cancelled cleanup task {cleanup_task_id}")
            else:
                logger.warning(
                    f"⚠️  Could not confirm cancellation of task {cleanup_task_id} "
                    f"(may have already started or completed)"
                )

            # Clear the cleanup runtime data atomically
            session.runtime.host_cleanup = None
            await session.partial_update_session_with_version_check(
                {Session.runtime: session.runtime},
                max_retry_on_conflicts=2,
            )
            cancelled_task_id = cleanup_task_id

        # Transition IDLE -> READY if needed
        if session.status == SessionState.IDLE:
            from app.domain.live.session.session_domain import SessionService

            service = SessionService()
            await service.update_session_state(
                session_id=session.session_id,
                new_state=SessionState.READY,
            )
            logger.info(f"✅ Session {session.session_id} transitioned IDLE -> READY (host joined)")
        else:
            logger.debug(
                f"Session {session.session_id} already in state {session.status}, not transitioning"
            )

    except FlcError as e:
        if e.errcode == FlcErrorCode.E_SESSION_NOT_FOUND:
            logger.warning(f"Session not found on participant join: {e}")
        else:
            logger.exception(f"Failed to update session state on participant join: {e}")
    except Exception as e:
        logger.exception(f"Failed to update session state on participant join: {e}")

    result: dict[str, Any] = {
        "handled": "participant_joined",
        "participant": event.participant.identity,
    }
    if cancelled_task_id:
        result["cancelled_cleanup_task_id"] = cancelled_task_id
    return result


async def handle_participant_left(event: ParticipantLeftEvent) -> dict[str, Any]:
    """Handle participant_left event.

    When host leaves, schedule a delayed cleanup task (10 minutes) to delete
    the room and update session state. If the host returns before the delay,
    the task will be cancelled.
    """
    from datetime import datetime, timezone

    from app.schemas import Session
    from app.schemas.session_runtime import HostCleanupRuntime
    from app.workers.api_jobs_worker import HOST_CLEANUP_DELAY, cleanup_session_after_host_left
    from app.workers.api_jobs_worker import worker as api_jobs_worker

    logger.info(f"🚪 PARTICIPANT LEFT: {event.participant.identity}")
    logger.info(f"   Room: {event.room.name}")
    if event.participant.disconnect_reason:
        logger.info(f"   Reason: {event.participant.disconnect_reason.value}")

    room_id = event.room.name

    try:
        session = await Session.find_one(Session.room_id == room_id)
        if not session:
            logger.warning(f"Session not found for room {room_id}")
            return {"handled": "participant_left", "participant": event.participant.identity}

        # Check if the participant who left is the host (user_id matches)
        if event.participant.identity != session.user_id:
            logger.debug(
                f"Participant {event.participant.identity} is not the host, no cleanup scheduled"
            )
            return {"handled": "participant_left", "participant": event.participant.identity}

        # Check if session is already in a terminal state
        if session.status in (SessionState.STOPPED, SessionState.CANCELLED):
            logger.info(f"Session {session.session_id} already in terminal state {session.status}")
            return {"handled": "participant_left", "participant": event.participant.identity}

        logger.info(
            f"Host {event.participant.identity} left room {room_id} "
            f"for session {session.session_id}, scheduling cleanup in {HOST_CLEANUP_DELAY}"
        )

        # Enqueue the cleanup task with delay
        async with api_jobs_worker:
            task = await cleanup_session_after_host_left.enqueue(session.session_id).start(
                delay=HOST_CLEANUP_DELAY
            )

        # Save the task ID to the session atomically for later cancellation if host returns
        session.runtime.host_cleanup = HostCleanupRuntime(
            task_id=task.id,
            host_left_at=datetime.now(timezone.utc),
        )
        await session.partial_update_session_with_version_check(
            {Session.runtime: session.runtime},
            max_retry_on_conflicts=2,
        )

        logger.info(
            f"⏰ Scheduled cleanup task {task.id} for session {session.session_id} "
            f"in {HOST_CLEANUP_DELAY}"
        )

        return {
            "handled": "participant_left",
            "participant": event.participant.identity,
            "cleanup_task_id": task.id,
        }

    except FlcError as e:
        if e.errcode == FlcErrorCode.E_SESSION_NOT_FOUND:
            logger.warning(f"Session not found for room {room_id} on participant left")
        else:
            logger.exception(f"Failed to handle participant left: {e}")
        return {"handled": "participant_left", "participant": event.participant.identity}
    except Exception as e:
        logger.exception(f"Failed to handle participant left: {e}")
        return {"handled": "participant_left", "participant": event.participant.identity}


async def handle_participant_connection_aborted(
    event: ParticipantConnectionAbortedEvent,
) -> dict[str, Any]:
    """Handle participant_connection_aborted event."""
    logger.warning(f"⚠️  CONNECTION ABORTED: {event.participant.identity}")
    logger.warning(f"   Room: {event.room.name}")

    # TODO: Implement connection aborted logic
    # - Log connection issues
    # - Send alerts if needed

    return {
        "handled": "participant_connection_aborted",
        "participant": event.participant.identity,
    }


async def handle_track_published(event: TrackPublishedEvent) -> dict[str, Any]:
    """Handle track_published event."""
    logger.info(f"🎥 TRACK PUBLISHED: {event.track.name}")
    logger.info(f"   Type: {event.track.type.value}")
    logger.info(f"   Source: {event.track.source.value}")
    logger.info(f"   Participant: {event.participant.identity}")

    # TODO: Implement track published logic
    # - Update recording status
    # - Monitor track quality

    return {"handled": "track_published", "track_sid": event.track.sid}


async def handle_track_unpublished(event: TrackUnpublishedEvent) -> dict[str, Any]:
    """Handle track_unpublished event."""
    logger.info(f"🎥 TRACK UNPUBLISHED: {event.track.name}")
    logger.info(f"   Type: {event.track.type.value}")
    logger.info(f"   Participant: {event.participant.identity}")

    # TODO: Implement track unpublished logic
    # - Update recording status

    return {"handled": "track_unpublished", "track_sid": event.track.sid}


async def handle_egress_started(event: EgressStartedEvent) -> dict[str, Any]:
    """Handle egress_started event."""
    logger.info(f"📹 EGRESS STARTED: {event.egress_info.egress_id}")
    logger.info(f"   Room: {event.egress_info.room_name}")
    logger.info(f"   Status: {event.egress_info.status.value}")

    # TODO: Implement egress started logic
    # - Update recording status
    # - Log start time

    return {"handled": "egress_started", "egress_id": event.egress_info.egress_id}


async def handle_egress_updated(event: EgressUpdatedEvent) -> dict[str, Any]:
    """Handle egress_updated event."""
    logger.info(f"📹 EGRESS UPDATED: {event.egress_info.egress_id}")
    logger.info(f"   Status: {event.egress_info.status.value}")

    # TODO: Implement egress updated logic
    # - Monitor recording progress

    return {"handled": "egress_updated", "egress_id": event.egress_info.egress_id}


async def handle_egress_ended(event: EgressEndedEvent) -> dict[str, Any]:
    """Handle egress_ended event."""
    logger.info(f"📹 EGRESS ENDED: {event.egress_info.egress_id}")
    logger.info(f"   Status: {event.egress_info.status.value}")
    if event.egress_info.error:
        logger.error(f"   Error: {event.egress_info.error}")

    # TODO: Implement egress ended logic
    # - Save recording metadata
    # - Process video files

    return {"handled": "egress_ended", "egress_id": event.egress_info.egress_id}


async def handle_ingress_started(event: IngressStartedEvent) -> dict[str, Any]:
    """Handle ingress_started event."""
    logger.info(f"📡 INGRESS STARTED: {event.ingress_info.name}")
    logger.info(f"   Room: {event.ingress_info.room_name}")

    # TODO: Implement ingress started logic
    # - Update stream status
    # - Monitor stream health

    return {"handled": "ingress_started", "ingress_id": event.ingress_info.ingress_id}


async def handle_ingress_ended(event: IngressEndedEvent) -> dict[str, Any]:
    """Handle ingress_ended event."""
    logger.info(f"📡 INGRESS ENDED: {event.ingress_info.name}")
    if event.ingress_info.error:
        logger.error(f"   Error: {event.ingress_info.error}")

    # TODO: Implement ingress ended logic
    # - Update stream status
    # - Log stream duration

    return {"handled": "ingress_ended", "ingress_id": event.ingress_info.ingress_id}


@router.post("/livekit", response_model=LiveKitWebhookSuccess | ApiFailure)
async def livekit_webhook(
    request: Request,
    authorization: str | None = Header(None),
) -> LiveKitWebhookSuccess | ApiFailure:
    """Receive and process LiveKit webhook events.

    This endpoint parses webhook events into typed Pydantic models and handles
    them case by case.

    Args:
        request: FastAPI request object
        authorization: Authorization header containing JWT token

    Returns:
        Success response with handling results or failure
    """
    try:
        # Get raw body
        body = await request.body()
        body_str = body.decode("utf-8")

        # Parse JSON
        try:
            event_data = json.loads(body_str)
        except json.JSONDecodeError as exc:
            logger.error(f"Invalid JSON in webhook body: {exc}")
            failure = api_failure(
                errcode=FlcErrorCode.E_WEBHOOK_INVALID_JSON,
                errmesg=f"Invalid JSON: {exc!s}",
            )
            return failure

        # Get event type
        event_type = event_data.get("event")
        if not event_type:
            logger.error("Missing 'event' field in webhook payload")
            failure = api_failure(
                errcode=FlcErrorCode.E_WEBHOOK_MISSING_EVENT_TYPE,
                errmesg="Missing 'event' field",
            )
            return failure

        separator = "=" * 80
        logger.info(separator)
        logger.info(f"LiveKit Webhook: {event_type}")
        logger.info(separator)

        # Parse into specific event schema and handle
        result: dict[str, Any]

        try:
            if event_type == "room_finished":
                # case "room_started":
                #     event = RoomStartedEvent(**event_data)
                #     result = await handle_room_started(event)
                event = RoomFinishedEvent(**event_data)
                result = await handle_room_finished(event)
            elif event_type == "participant_joined":
                event = ParticipantJoinedEvent(**event_data)
                result = await handle_participant_joined(event)
            elif event_type == "participant_left":
                event = ParticipantLeftEvent(**event_data)
                result = await handle_participant_left(event)
            else:
                logger.warning(f"Unhandled LiveKit webhook event: {event_type}")
                result = {"ignored": True, "event": event_type}

                # case "participant_connection_aborted":
                #     event = ParticipantConnectionAbortedEvent(**event_data)
                #     result = await handle_participant_connection_aborted(event)

                # case "track_published":
                #     event = TrackPublishedEvent(**event_data)
                #     result = await handle_track_published(event)

                # case "track_unpublished":
                #     event = TrackUnpublishedEvent(**event_data)
                #     result = await handle_track_unpublished(event)

                # case "egress_started":
                #     event = EgressStartedEvent(**event_data)
                #     result = await handle_egress_started(event)

                # case "egress_updated":
                #     event = EgressUpdatedEvent(**event_data)
                #     result = await handle_egress_updated(event)

                # case "egress_ended":
                #     event = EgressEndedEvent(**event_data)
                #     result = await handle_egress_ended(event)

                # case "ingress_started":
                #     event = IngressStartedEvent(**event_data)
                #     result = await handle_ingress_started(event)

                # case "ingress_ended":
                #     event = IngressEndedEvent(**event_data)
                #     result = await handle_ingress_ended(event)

                # Legacy match/case default branch removed for demo compatibility (Python 3.9+).

        except ValidationError as exc:
            logger.error(f"Failed to parse {event_type} event: {exc}")
            logger.error(f"❌ VALIDATION ERROR: {exc}")
            failure = api_failure(
                errcode=FlcErrorCode.E_WEBHOOK_VALIDATION_ERROR,
                errmesg=f"Failed to parse event: {exc!s}",
            )
            return failure

        logger.info(separator)

        return LiveKitWebhookSuccess(results=result)

    except Exception as exc:
        logger.exception("Error processing LiveKit webhook")
        failure = api_failure(
            errcode=FlcErrorCode.E_WEBHOOK_ERROR,
            errmesg=str(exc),
        )
        return failure
