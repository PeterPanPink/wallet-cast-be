"""Tests for SessionStateMachine state transitions."""

from app.domain.live.session.session_state_machine import SessionStateMachine
from app.schemas import SessionState


class TestCanTransition:
    """Tests for SessionStateMachine.can_transition method."""

    def test_idle_to_ready_valid(self):
        """Test IDLE -> READY is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.IDLE, SessionState.READY) is True

    def test_idle_to_cancelled_valid(self):
        """Test IDLE -> CANCELLED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.IDLE, SessionState.CANCELLED) is True

    def test_idle_to_aborted_valid(self):
        """Test IDLE -> ABORTED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.IDLE, SessionState.ABORTED) is True

    def test_idle_to_live_invalid(self):
        """Test IDLE -> LIVE is an invalid transition (must go through READY, PUBLISHING)."""
        assert SessionStateMachine.can_transition(SessionState.IDLE, SessionState.LIVE) is False

    def test_ready_to_publishing_valid(self):
        """Test READY -> PUBLISHING is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.READY, SessionState.PUBLISHING) is True
        )

    def test_ready_to_cancelled_valid(self):
        """Test READY -> CANCELLED is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.READY, SessionState.CANCELLED) is True
        )

    def test_ready_to_idle_valid(self):
        """Test READY -> IDLE is a valid transition (host left before start)."""
        assert SessionStateMachine.can_transition(SessionState.READY, SessionState.IDLE) is True

    def test_ready_to_aborted_valid(self):
        """Test READY -> ABORTED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.READY, SessionState.ABORTED) is True

    def test_publishing_to_live_valid(self):
        """Test PUBLISHING -> LIVE is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.PUBLISHING, SessionState.LIVE) is True
        )

    def test_publishing_to_cancelled_valid(self):
        """Test PUBLISHING -> CANCELLED is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.PUBLISHING, SessionState.CANCELLED)
            is True
        )

    def test_publishing_to_ready_valid(self):
        """Test PUBLISHING -> READY is a valid transition (egress failed before going live)."""
        assert (
            SessionStateMachine.can_transition(SessionState.PUBLISHING, SessionState.READY) is True
        )

    def test_publishing_to_aborted_valid(self):
        """Test PUBLISHING -> ABORTED is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.PUBLISHING, SessionState.ABORTED)
            is True
        )

    def test_live_to_ending_valid(self):
        """Test LIVE -> ENDING is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.LIVE, SessionState.ENDING) is True

    def test_live_to_aborted_valid(self):
        """Test LIVE -> ABORTED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.LIVE, SessionState.ABORTED) is True

    def test_live_to_cancelled_invalid(self):
        """Test LIVE -> CANCELLED is invalid (once live, must go through ENDING)."""
        assert (
            SessionStateMachine.can_transition(SessionState.LIVE, SessionState.CANCELLED) is False
        )

    def test_ending_to_stopped_valid(self):
        """Test ENDING -> STOPPED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.ENDING, SessionState.STOPPED) is True

    def test_ending_to_aborted_valid(self):
        """Test ENDING -> ABORTED is a valid transition."""
        assert SessionStateMachine.can_transition(SessionState.ENDING, SessionState.ABORTED) is True

    def test_aborted_to_stopped_valid(self):
        """Test ABORTED -> STOPPED is a valid transition."""
        assert (
            SessionStateMachine.can_transition(SessionState.ABORTED, SessionState.STOPPED) is True
        )

    def test_cancelled_no_transitions(self):
        """Test CANCELLED is terminal - no valid transitions."""
        assert (
            SessionStateMachine.can_transition(SessionState.CANCELLED, SessionState.IDLE) is False
        )
        assert (
            SessionStateMachine.can_transition(SessionState.CANCELLED, SessionState.READY) is False
        )
        assert (
            SessionStateMachine.can_transition(SessionState.CANCELLED, SessionState.STOPPED)
            is False
        )

    def test_stopped_no_transitions(self):
        """Test STOPPED is terminal - no valid transitions."""
        assert SessionStateMachine.can_transition(SessionState.STOPPED, SessionState.IDLE) is False
        assert SessionStateMachine.can_transition(SessionState.STOPPED, SessionState.READY) is False
        assert (
            SessionStateMachine.can_transition(SessionState.STOPPED, SessionState.CANCELLED)
            is False
        )


class TestIsTerminal:
    """Tests for SessionStateMachine.is_terminal method."""

    def test_cancelled_is_terminal(self):
        """Test CANCELLED is a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.CANCELLED) is True

    def test_stopped_is_terminal(self):
        """Test STOPPED is a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.STOPPED) is True

    def test_idle_not_terminal(self):
        """Test IDLE is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.IDLE) is False

    def test_ready_not_terminal(self):
        """Test READY is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.READY) is False

    def test_publishing_not_terminal(self):
        """Test PUBLISHING is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.PUBLISHING) is False

    def test_live_not_terminal(self):
        """Test LIVE is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.LIVE) is False

    def test_ending_not_terminal(self):
        """Test ENDING is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.ENDING) is False

    def test_aborted_not_terminal(self):
        """Test ABORTED is not a terminal state."""
        assert SessionStateMachine.is_terminal(SessionState.ABORTED) is False


class TestGetValidTransitions:
    """Tests for SessionStateMachine.get_valid_transitions method."""

    def test_idle_transitions(self):
        """Test valid transitions from IDLE state."""
        transitions = SessionStateMachine.get_valid_transitions(SessionState.IDLE)
        assert SessionState.READY in transitions
        assert SessionState.CANCELLED in transitions
        assert SessionState.ABORTED in transitions
        assert len(transitions) == 3

    def test_live_transitions(self):
        """Test valid transitions from LIVE state."""
        transitions = SessionStateMachine.get_valid_transitions(SessionState.LIVE)
        assert SessionState.ENDING in transitions
        assert SessionState.ABORTED in transitions
        assert len(transitions) == 2

    def test_cancelled_transitions_empty(self):
        """Test terminal CANCELLED has no valid transitions."""
        transitions = SessionStateMachine.get_valid_transitions(SessionState.CANCELLED)
        assert len(transitions) == 0

    def test_stopped_transitions_empty(self):
        """Test terminal STOPPED has no valid transitions."""
        transitions = SessionStateMachine.get_valid_transitions(SessionState.STOPPED)
        assert len(transitions) == 0


class TestGetValidSources:
    """Tests for SessionStateMachine.get_valid_sources method."""

    def test_ready_sources(self):
        """Test states that can transition to READY."""
        sources = SessionStateMachine.get_valid_sources(SessionState.READY)
        assert SessionState.IDLE in sources
        assert SessionState.PUBLISHING in sources  # Egress failure case

    def test_stopped_sources(self):
        """Test states that can transition to STOPPED."""
        sources = SessionStateMachine.get_valid_sources(SessionState.STOPPED)
        assert SessionState.ENDING in sources
        assert SessionState.ABORTED in sources

    def test_cancelled_sources(self):
        """Test states that can transition to CANCELLED."""
        sources = SessionStateMachine.get_valid_sources(SessionState.CANCELLED)
        assert SessionState.IDLE in sources
        assert SessionState.READY in sources
        assert SessionState.PUBLISHING in sources

    def test_idle_sources(self):
        """Test states that can transition to IDLE (only READY for host-left case)."""
        sources = SessionStateMachine.get_valid_sources(SessionState.IDLE)
        assert SessionState.READY in sources
