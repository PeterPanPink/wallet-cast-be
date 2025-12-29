"""Base service for session operations."""

from beanie.operators import In
from loguru import logger

from app.shared.domain.entity_change import utc_now
from app.schemas import Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.services.integrations.livekit_service import livekit_service
from app.services.integrations.mux_service import mux_service
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from .session_state_machine import SessionStateMachine


class BaseService:
    """Base service with shared session operation methods."""

    def __init__(self):
        """Initialize BaseService with provider services."""
        self.livekit = livekit_service
        self.mux = mux_service

    async def _get_session_by_id(self, session_id: str) -> Session | None:
        """
        Retrieve a session by session_id.

        Args:
            session_id: The session identifier

        Returns:
            Session document if found, None otherwise
        """
        return await Session.find_one(Session.session_id == session_id)

    async def _get_active_session_by_room_id(self, room_id: str) -> Session | None:
        """
        Retrieve a session by room_id

        Args:
            room_id: The room identifier

        Returns:
            Session document if found, None otherwise
        """
        return await Session.find_one(
            Session.room_id == room_id,
            In(Session.status, SessionState.active_states()),
        )

    async def _get_last_session_by_room_id(self, room_id: str) -> Session | None:
        """
        Retrieve the most recent session by room_id (any state).

        Args:
            room_id: The room identifier

        Returns:
            Most recent Session document if found, None otherwise
        """
        return await Session.find_one(
            Session.room_id == room_id,
            sort=[("-created_at", -1)],
        )

    def _resolve_provider_config(self, configs: SessionRuntime | None) -> SessionRuntime:
        """Resolve provider config from SessionRuntime object."""
        return configs or SessionRuntime()

    async def update_session_state(self, session: Session, new_state: SessionState) -> Session:
        """
        Update session state with validation and timestamp updates.

        Public method for state transitions from webhooks and endpoints.

        Args:
            session: Session document to update
            new_state: Target state to transition to

        Returns:
            Updated session document

        Raises:
            ValueError: If state transition is invalid
        """
        # No-op if already in target state
        if session.status == new_state:
            logger.info(f"Session {session.room_id} already in state {new_state}, skipping")
            return session

        if not SessionStateMachine.can_transition(session.status, new_state):
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg=f"Invalid state transition: {session.status} -> {new_state}",
                status_code=HttpStatusCode.BAD_REQUEST,
            )

        # Update state
        session.status = new_state
        session.updated_at = utc_now()

        # Update lifecycle timestamps
        if new_state == SessionState.LIVE and not session.started_at:
            session.started_at = utc_now()
        elif new_state in {
            SessionState.STOPPED,
            SessionState.ABORTED,
            SessionState.CANCELLED,
        }:
            if not session.stopped_at:
                session.stopped_at = utc_now()

        # Save to database
        updates = {
            Session.status: session.status,
            Session.updated_at: session.updated_at,
        }
        if new_state == SessionState.LIVE and session.started_at:
            updates[Session.started_at] = session.started_at
        elif new_state in {
            SessionState.STOPPED,
            SessionState.ABORTED,
            SessionState.CANCELLED,
        } and session.stopped_at:
            updates[Session.stopped_at] = session.stopped_at

        await session.partial_update_session_with_version_check(
            updates,
            max_retry_on_conflicts=0,
        )

        logger.info(f"Session {session.room_id} state updated to {new_state}")

        return session
