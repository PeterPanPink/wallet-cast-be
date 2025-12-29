"""Common enums used across schemas."""

from enum import Enum


class SessionState(str, Enum):
    """Session lifecycle states.

    State Transition Flow:

    IDLE → READY → PUBLISHING → LIVE → ENDING → STOPPED
      ↓      ↓         ↓         ↓
    CANCELLED  CANCELLED  CANCELLED  ABORTED → STOPPED

    State Descriptions:
    - IDLE: Session created, awaiting host. Set by create_session().
    - SCHEDULED: Session scheduled for future (not yet implemented).
    - READY: Host joined the room. Set by LiveKit participant_joined webhook.
    - PUBLISHING: Streaming started to Mux. Set by start_live() call.
    - LIVE: Stream confirmed active on Mux CDN. Set by Mux video.live_stream.active webhook.
    - ENDING: Stream stop initiated. Set by end_live() or end_session() call (only from LIVE).
    - ABORTED: Stream failed unexpectedly. Set on critical errors.
    - CANCELLED: Session cancelled before going live. Set by end_session() from IDLE/READY/PUBLISHING.
    - STOPPED: Stream confirmed stopped, room deleted. Set by Mux idle/disconnected webhook (from ENDING) or LiveKit room_finished webhook.

    Terminal states (no further transitions): CANCELLED, STOPPED
    """

    IDLE = "idle"
    SCHEDULED = "scheduled"
    READY = "ready"
    PUBLISHING = "publishing"
    LIVE = "live"
    ENDING = "ending"
    ABORTED = "aborted"
    CANCELLED = "cancelled"
    STOPPED = "stopped"

    def __str__(self) -> str:
        return self.value

    @classmethod
    def active_states(cls) -> list["SessionState"]:
        """States considered 'active' for a session."""
        return [
            SessionState.IDLE,
            SessionState.READY,
            SessionState.PUBLISHING,
            SessionState.LIVE,
            SessionState.ENDING,
        ]


__all__ = ["SessionState"]
