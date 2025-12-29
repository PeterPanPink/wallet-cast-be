"""Tests for EndSessionOperations domain logic."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.live.session._end import EndSessionOperations
from app.schemas import Session, SessionState
from app.schemas.session_runtime import LiveKitRuntime, MuxRuntime, SessionRuntime
from app.utils.flc_errors import FlcError, FlcErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestEndSession:
    """Tests for EndSessionOperations.end_session method."""

    async def test_end_session_from_idle_becomes_cancelled(self, beanie_db):
        """Test ending IDLE session transitions to CANCELLED."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_end_idle",
            room_id="end-idle-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_end_idle")

        # Assert
        assert result.status == SessionState.CANCELLED

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_end_idle")
        assert saved is not None
        assert saved.status == SessionState.CANCELLED
        assert saved.stopped_at is not None

    async def test_end_session_from_ready_becomes_cancelled(self, beanie_db):
        """Test ending READY session transitions to CANCELLED."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_end_ready",
            room_id="end-ready-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_end_ready")

        # Assert
        assert result.status == SessionState.CANCELLED

    async def test_end_session_from_publishing_becomes_cancelled(self, beanie_db):
        """Test ending PUBLISHING session transitions to CANCELLED."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_end_pub",
            room_id="end-pub-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_end_pub")

        # Assert
        assert result.status == SessionState.CANCELLED

    async def test_end_session_from_live_becomes_ending(self, beanie_db):
        """Test ending LIVE session transitions to ENDING and stops egress."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_end_live",
            room_id="end-live-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                livekit=LiveKitRuntime(egress_id="EG_live"),
                mux=MuxRuntime(mux_stream_id="mux_live"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        with patch.object(
            ops._egress,
            "end_live",
            new_callable=AsyncMock,
        ) as mock_end_live:
            result = await ops.end_session("se_end_live")

            # Assert - end_live should be called for LIVE sessions
            mock_end_live.assert_called_once_with(
                room_name="end-live-room",
                egress_id="EG_live",
                mux_stream_id="mux_live",
            )

        assert result.status == SessionState.ENDING

    async def test_end_session_from_ending_becomes_stopped(self, beanie_db):
        """Test ending ENDING session transitions through ABORTED to STOPPED."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_end_ending",
            room_id="end-ending-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.ENDING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_end_ending")

        # Assert - Should be STOPPED (via ABORTED) since session was ending
        assert result.status == SessionState.STOPPED

    async def test_end_session_not_found(self, beanie_db):
        """Test ending non-existent session raises FlcError."""
        # Arrange
        ops = EndSessionOperations()

        # Act & Assert
        with pytest.raises(FlcError) as exc_info:
            await ops.end_session("se_nonexistent")
        assert exc_info.value.errcode == FlcErrorCode.E_SESSION_NOT_FOUND

    async def test_end_session_egress_stop_failure_continues(self, beanie_db):
        """Test that egress stop failure doesn't block state update."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_egress_fail",
            room_id="egress-fail-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                livekit=LiveKitRuntime(egress_id="EG_fail"),
                mux=MuxRuntime(mux_stream_id="mux_fail"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act - Simulate egress stop failure
        with patch.object(
            ops._egress,
            "end_live",
            new_callable=AsyncMock,
            side_effect=Exception("Egress stop failed"),
        ):
            result = await ops.end_session("se_egress_fail")

        # Assert - State should still update despite egress failure
        assert result.status == SessionState.ENDING

    async def test_end_session_without_egress_info(self, beanie_db):
        """Test ending session without egress info (no egress_id/mux_stream_id)."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_no_egress",
            room_id="no-egress-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),  # No egress info
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        with patch.object(
            ops._egress,
            "end_live",
            new_callable=AsyncMock,
        ) as mock_end_live:
            result = await ops.end_session("se_no_egress")

            # end_live should NOT be called without egress info
            mock_end_live.assert_not_called()

        # Assert - State should still update
        assert result.status == SessionState.ENDING

    async def test_end_session_stopped_state_skips_transition(self, beanie_db):
        """Test ending already STOPPED session skips state transition."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_already_stopped",
            room_id="stopped-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,  # Already terminal
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_already_stopped")

        # Assert - Should remain STOPPED (no transition)
        assert result.status == SessionState.STOPPED

    async def test_end_session_cancelled_state_skips_transition(self, beanie_db):
        """Test ending already CANCELLED session skips state transition."""
        # Arrange
        ops = EndSessionOperations()

        session = Session(
            session_id="se_already_cancelled",
            room_id="cancelled-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.CANCELLED,  # Already terminal
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.end_session("se_already_cancelled")

        # Assert - Should remain CANCELLED (no transition)
        assert result.status == SessionState.CANCELLED
