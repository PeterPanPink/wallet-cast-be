"""Session state machine for managing state transitions."""

from app.schemas import SessionState


class SessionStateMachine:
    """State machine for managing session state transitions.

    State flow with triggers:
    - IDLE (session created) -> READY (host joined the room, captured in LiveKit webhook) | CANCELLED
    - READY -> PUBLISHING (start-live triggered) | CANCELLED | IDLE
    - PUBLISHING -> LIVE (confirmed in Mux webhook: video.live_stream.active) | CANCELLED | READY | ABORTED
    - LIVE -> ENDING (end-live triggered) | ABORTED
    - ENDING -> STOPPED (confirmed in Mux webhook: video.live_stream.idle/disconnected OR LiveKit room_finished)
    - ABORTED -> STOPPED (cleanup/room deletion)
    - CANCELLED/STOPPED are terminal states

    Detailed triggers:
    1. IDLE: Set when session is created via create_session()
    2. READY: Set when host joins room (LiveKit participant_joined webhook)
    3. PUBLISHING: Set when start_live() is called to begin streaming to Mux
    4. LIVE: Set when Mux confirms stream is active (Mux video.live_stream.active webhook)
    5. ENDING: Set when end_live() is called to stop streaming (only from LIVE)
    6. STOPPED: Set when stream confirmed stopped (Mux webhook) or room deleted (LiveKit webhook)
    7. ABORTED: Set on unexpected errors/failures during streaming
    8. CANCELLED: Set by end_session() when ending before going live (from IDLE/READY/PUBLISHING)
    """

    # State transition map defining valid state flows
    TRANSITIONS: dict[SessionState, set[SessionState]] = {
        SessionState.IDLE: {
            SessionState.READY,
            SessionState.CANCELLED,
            SessionState.ABORTED,
        },
        SessionState.READY: {
            SessionState.PUBLISHING,
            SessionState.CANCELLED,
            SessionState.IDLE,
            SessionState.ABORTED,
        },
        SessionState.PUBLISHING: {
            SessionState.LIVE,
            SessionState.CANCELLED,
            SessionState.READY,
            SessionState.ABORTED,
        },
        SessionState.LIVE: {
            SessionState.ENDING,
            SessionState.ABORTED,
        },
        SessionState.ENDING: {SessionState.STOPPED, SessionState.ABORTED},
        SessionState.ABORTED: {SessionState.STOPPED, SessionState.CANCELLED},
        SessionState.CANCELLED: set(),
        SessionState.STOPPED: set(),
    }

    # Terminal states that cannot transition further
    TERMINAL_STATES: set[SessionState] = {SessionState.CANCELLED, SessionState.STOPPED}

    @classmethod
    def can_transition(cls, current: SessionState, new: SessionState) -> bool:
        """Check if state transition is valid.

        Args:
            current: Current session state
            new: Target state to transition to

        Returns:
            True if transition is valid, False otherwise
        """
        return new in cls.TRANSITIONS.get(current, set())

    @classmethod
    def is_terminal(cls, state: SessionState) -> bool:
        """Check if a state is terminal (no further transitions allowed).

        Args:
            state: Session state to check

        Returns:
            True if state is terminal, False otherwise
        """
        return state in cls.TERMINAL_STATES

    @classmethod
    def get_valid_transitions(cls, state: SessionState) -> set[SessionState]:
        """Get all valid transitions from a given state.

        Args:
            state: Current session state

        Returns:
            Set of valid target states
        """
        return cls.TRANSITIONS.get(state, set())

    @classmethod
    def get_valid_sources(cls, target: SessionState) -> set[SessionState]:
        """Get all states that can transition to the target state.

        Args:
            target: Target session state

        Returns:
            Set of states that can transition to the target
        """
        return {state for state, targets in cls.TRANSITIONS.items() if target in targets}
