"""Session domain service - Batch operations with Beanie ODM."""

from app.schemas import Session, SessionState

from ._egress import EgressOperations
from ._end import EndSessionOperations
from ._ingress import IngressOperations
from ._sessions import SessionOperations
from .session_models import (
    LiveStreamStartResponse,
    SessionCreateParams,
    SessionListResponse,
    SessionResponse,
    SessionUpdateParams,
)


class SessionService:
    """Batch-oriented session service."""

    def __init__(self):
        self._sessions = SessionOperations()
        self._ingress = IngressOperations()
        self._egress = EgressOperations()
        self._end = EndSessionOperations()

    # ==================== SESSIONS ====================

    async def create_session(
        self,
        params: SessionCreateParams,
    ) -> SessionResponse:
        """Create a new session.

        Raises AppError if an active session already exists
        """
        return await self._sessions.create_session(params=params)

    async def get_session(
        self,
        session_id: str,
    ) -> SessionResponse:
        """Get a single session by session_id.

        Raises AppError if session not found.
        """
        return await self._sessions.get_session(session_id=session_id)

    async def get_active_session_by_room_id(
        self,
        room_id: str,
    ) -> SessionResponse:
        """Get an active session by room_id.

        Raises AppError if session not found or not in an active state.
        """
        return await self._sessions.get_active_session_by_room_id(room_id=room_id)

    async def get_last_session_by_room_id(
        self,
        room_id: str,
    ) -> SessionResponse:
        """Get the most recent session by room_id (regardless of status).

        Raises AppError if no session found for room_id.
        """
        return await self._sessions.get_last_session_by_room_id(room_id=room_id)

    async def get_active_session_by_channel(
        self,
        channel_id: str,
    ) -> SessionResponse:
        """Get the active session for a channel.

        Raises AppError if no active session found for channel.
        """
        return await self._sessions.get_active_session_by_channel(channel_id=channel_id)

    async def recreate_session_from_stopped(
        self,
        stopped_session: Session,
    ) -> SessionResponse:
        """Create a new READY session from a stopped session.

        This is called after a session transitions to STOPPED to allow
        the user to start a new stream using the same room_id.

        Args:
            stopped_session: The session that was just stopped

        Returns:
            SessionResponse for the newly created session

        Raises:
            ValueError: If session is not in STOPPED state
            AppError: If channel is not found or inactive
        """
        return await self._sessions.recreate_session_from_stopped(
            stopped_session=stopped_session,
        )

    async def recreate_session_from_terminal(
        self,
        terminal_session: Session,
    ) -> SessionResponse:
        """Create a new READY session from a terminal session (STOPPED or CANCELLED).

        This is called after a session transitions to a terminal state to allow
        the user to start a new stream using the same room_id.

        Args:
            terminal_session: The session that reached a terminal state

        Returns:
            SessionResponse for the newly created session

        Raises:
            ValueError: If session is not in a terminal state (STOPPED or CANCELLED)
            AppError: If channel is not found or inactive
        """
        return await self._sessions.recreate_session_from_terminal(
            terminal_session=terminal_session,
        )

    async def list_sessions(
        self,
        cursor: str | None = None,
        page_size: int = 20,
        channel_id: str | None = None,
        user_id: str | None = None,
        status: list[SessionState] | SessionState | None = None,
    ) -> SessionListResponse:
        """Return paginated sessions with optional filters."""
        return await self._sessions.list_sessions(
            cursor=cursor,
            page_size=page_size,
            channel_id=channel_id,
            user_id=user_id,
            status=status,
        )

    async def update_session(
        self,
        session_id: str,
        params: SessionUpdateParams,
    ) -> SessionResponse:
        """Update session metadata.

        Raises AppError if session not found.
        """
        return await self._sessions.update_session(
            session_id=session_id,
            params=params,
        )

    # ==================== INGRESS ====================

    async def create_room(
        self,
        room_name: str,
        metadata: str | None = None,
        empty_timeout: int = 300,
        max_participants: int = 100,
    ):
        """Create a LiveKit room.

        Args:
            room_name: Unique name for the room
            session: Optional Session document to update state to READY after room creation
            metadata: Optional JSON string containing room metadata
            empty_timeout: Timeout in seconds before room closes when empty
            max_participants: Maximum number of participants allowed

        Returns:
            Room object with .name, .sid, .metadata attributes
        """
        return await self._ingress.create_room(
            room_name=room_name,
            metadata=metadata,
            empty_timeout=empty_timeout,
            max_participants=max_participants,
        )

    async def delete_room(
        self,
        room_name: str,
    ) -> None:
        """Delete a LiveKit room.

        This is the counterpart to create_room and should be called when
        the room is no longer needed. Typically called after a session
        has reached a terminal state (STOPPED, CANCELLED, ABORTED).

        Args:
            room_name: Room name (room_id) to delete

        Raises:
            AppError: If session not found for room
            Exception: If the LiveKit API request fails
        """
        return await self._ingress.delete_room(room_name=room_name)

    async def get_host_access_token(
        self,
        identity: str,
        room_name: str,
        display_name: str | None = None,
        metadata: str | None = None,
    ) -> str:
        """Generate a LiveKit access token for a host (with full permissions).

        Args:
            identity: Unique identity for the host participant
            room_name: Room name to grant access to
            display_name: Display name for the host (optional)
            metadata: Custom metadata string (optional)

        Returns:
            JWT token string
        """
        return await self._ingress.get_host_access_token(
            identity=identity,
            room_name=room_name,
            display_name=display_name,
            metadata=metadata,
        )

    async def get_guest_access_token(
        self,
        identity: str,
        room_name: str,
        display_name: str | None = None,
        metadata: str | None = None,
        can_publish: bool = True,
    ) -> str:
        """Generate a LiveKit access token for a guest/viewer.

        Args:
            identity: Unique identity for the guest participant
            room_name: Room name to grant access to
            display_name: Display name for the guest (optional)
            metadata: Custom metadata string (optional)
            can_publish: Whether guest can publish tracks (default: False)

        Returns:
            JWT token string
        """
        return await self._ingress.get_guest_access_token(
            identity=identity,
            room_name=room_name,
            display_name=display_name,
            metadata=metadata,
            can_publish=can_publish,
        )

    async def get_recorder_access_token(
        self,
        room_name: str,
        identity: str | None = None,
        display_name: str | None = None,
        metadata: str | None = None,
    ) -> str:
        """Generate a LiveKit access token for a recorder to join and record the live.

        Args:
            room_name: Room name to grant access to
            identity: Unique identity for the recorder participant (optional)
            display_name: Display name for the recorder (optional)
            metadata: Custom metadata string (optional)

        Returns:
            JWT token string
        """
        return await self._ingress.get_recorder_access_token(
            room_name=room_name,
            identity=identity,
            display_name=display_name,
            metadata=metadata,
        )

    async def update_room_metadata(
        self,
        room_name: str,
        metadata: str,
    ):
        """Update metadata for a LiveKit room.

        Args:
            room_name: Room name to update
            metadata: JSON string containing room metadata

        Returns:
            Room object with updated metadata
        """
        return await self._ingress.update_room_metadata(
            room_name=room_name,
            metadata=metadata,
        )

    async def update_participant(
        self,
        room_name: str,
        identity: str,
        name: str | None = None,
        metadata: str | None = None,
    ):
        """Update participant display name and/or metadata.

        Args:
            room_name: Room name where the participant is
            identity: Identity of the participant to update
            name: New display name for the participant (optional)
            metadata: New metadata for the participant (optional)

        Returns:
            ParticipantInfo object with updated participant details
        """
        return await self._ingress.update_participant(
            room_name=room_name,
            identity=identity,
            name=name,
            metadata=metadata,
        )

    # ==================== EGRESS ====================

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

        Args:
            room_name: Room name (session_id) to start live streaming for
            layout: Layout for the composite (default: "speaker")
            referer: HTTP Referer header to use as fallback for frontend base URL
            base_path: Frontend base path for recording URL (e.g., '/demo')
            width: Video width in pixels (default: 1920)
            height: Video height in pixels (default: 1080)
            is_mobile: Whether the request is from a mobile app (default: False)

        Returns:
            LiveStreamStartResponse with egress and Mux stream information
        """
        return await self._egress.start_live(
            room_name=room_name,
            layout=layout,
            referer=referer,
            base_path=base_path,
            width=width,
            height=height,
            is_mobile=is_mobile,
        )

    async def end_live(
        self,
        room_name: str,
        egress_id: str,
        mux_stream_id: str,
    ) -> None:
        """End live streaming by stopping LiveKit egress and completing Mux stream.

        Args:
            room_name: Room name (session_id) to end streaming for
            egress_id: LiveKit egress ID to stop
            mux_stream_id: Mux stream ID to complete
        """
        return await self._egress.end_live(
            room_name=room_name,
            egress_id=egress_id,
            mux_stream_id=mux_stream_id,
        )

    async def end_session(
        self,
        session_id: str,
    ) -> SessionResponse:
        """End a session by stopping egress and updating state.

        This performs session teardown:
        1. Stops LiveKit egress (if active)
        2. Completes Mux stream (if active)
        3. Updates session state (ENDING for live sessions, CANCELLED for non-live)

        Note: This does NOT delete the LiveKit room. Use delete_room() separately
        to clean up the room after the session has ended.

        Args:
            session_id: Session identifier for the session

        Returns:
            SessionResponse with updated state

        Raises:
            ValueError: If session not found or invalid state
        """
        return await self._end.end_session(session_id=session_id)

    # ==================== STATE MANAGEMENT ====================

    async def update_session_state(
        self,
        session_id: str,
        new_state: SessionState,
    ) -> Session:
        """
        Update session state with validation and timestamp updates.

        Public method for state transitions from webhooks and other services.

        Args:
            session_id: Session identifier for the session
            new_state: Target state to transition to

        Returns:
            Updated session document

        Raises:
            ValueError: If state transition is invalid or session not found
        """
        session = await self._sessions._get_session_by_id(session_id)
        if not session:
            from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

            raise AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg=f"Session not found: {session_id}",
                status_code=HttpStatusCode.NOT_FOUND,
            )

        return await self._sessions.update_session_state(session, new_state)
