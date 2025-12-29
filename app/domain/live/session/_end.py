"""Session ending operations."""

from loguru import logger

from app.schemas import SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

from ._base import BaseService
from ._egress import EgressOperations
from .session_models import SessionResponse


class EndSessionOperations(BaseService):
    """Operations for ending sessions."""

    def __init__(self):
        super().__init__()
        self._egress = EgressOperations()

    async def end_session(
        self,
        session_id: str,
    ) -> SessionResponse:
        """End a session by stopping egress and updating state.

        Note: This does NOT delete the LiveKit room. Use delete_room() separately
        to clean up the room after the session has ended.

        Args:
            session_id: Session identifier for the session

        Returns:
            SessionResponse with updated state

        Raises:
            FlcError: If session not found or invalid state
        """
        # Get the session
        session = await self._get_session_by_id(session_id)
        if not session:
            raise FlcError(
                errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found: {session_id}",
                status_code=FlcStatusCode.NOT_FOUND,
            )

        logger.info(f"Ending session {session_id} (current state: {session.status})")

        # Determine target state based on current state
        # Sessions that never went LIVE should be CANCELLED, not ENDING
        if session.status in {
            SessionState.IDLE,
            SessionState.READY,
            SessionState.PUBLISHING,
        }:
            target_state = SessionState.CANCELLED
            logger.info(
                f"Session {session_id} ending before going live, transitioning to CANCELLED"
            )
        elif session.status == SessionState.LIVE:
            target_state = SessionState.ENDING
            logger.info(f"Session {session_id} is live, transitioning to ENDING")
        elif session.status == SessionState.ENDING:
            # Transition through ABORTED to STOPPED for sessions that were ending
            target_state = SessionState.ABORTED
            logger.info(f"Session {session_id} is ending, transitioning to ABORTED then STOPPED")
        elif session.status == SessionState.ABORTED:
            # Already in ABORTED, transition to STOPPED
            target_state = SessionState.STOPPED
            logger.info(f"Session {session_id} is aborted, transitioning to STOPPED")
        else:
            # Already in terminal state or invalid state
            logger.warning(
                f"Session {session_id} in unexpected state {session.status}, skipping state transition"
            )
            target_state = None

        # Stop egress if active
        egress_id = session.runtime.livekit.egress_id if session.runtime.livekit else None
        mux_stream_id = session.runtime.mux.mux_stream_id if session.runtime.mux else None

        if egress_id and mux_stream_id:
            try:
                logger.info(
                    f"Stopping egress for session {session_id}: egress_id={egress_id}, mux_stream_id={mux_stream_id}"
                )
                await self._egress.end_live(
                    room_name=session.room_id,  # Use room_id for LiveKit
                    egress_id=egress_id,
                    mux_stream_id=mux_stream_id,
                )
                logger.info(f"Successfully stopped egress for session {session_id}")
            except Exception as e:
                logger.warning(
                    f"Failed to stop egress for session {session_id}: {e!s}",
                    exc_info=True,
                )
                # Continue with state update even if egress stop fails

        # Update session state
        # Note: ENDING state will transition to STOPPED when LiveKit webhook confirms room is deleted
        # CANCELLED is already a terminal state
        if target_state:
            try:
                updated_session = await self.update_session_state(session, target_state)
                logger.info(f"Session {session_id} state updated to {target_state}")

                # If we transitioned to ABORTED, continue to STOPPED
                if target_state == SessionState.ABORTED:
                    await self.update_session_state(updated_session, SessionState.STOPPED)
                    logger.info(f"Session {session_id} state updated to STOPPED")
            except Exception as e:
                logger.error(
                    f"Failed to update session {session_id} state to {target_state}: {e!s}",
                    exc_info=True,
                )
                raise

        # Refresh session to get latest state
        session = await self._get_session_by_id(session_id)
        if not session:
            raise FlcError(
                errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found after update: {session_id}",
                status_code=FlcStatusCode.NOT_FOUND,
            )

        return SessionResponse(**session.model_dump(exclude={"id"}, mode="json"))
