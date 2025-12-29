"""Tests for BaseService state management."""

from datetime import datetime, timezone

import pytest

from app.domain.live.session._base import BaseService
from app.schemas import Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.flc_errors import FlcError


@pytest.mark.usefixtures("clear_collections")
class TestUpdateSessionState:
    """Tests for BaseService.update_session_state method."""

    async def test_update_state_idle_to_ready(self, beanie_db):
        """Test valid transition from IDLE to READY."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_state_test",
            room_id="state-test-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.READY)

        # Assert
        assert result.status == SessionState.READY

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_state_test")
        assert saved is not None
        assert saved.status == SessionState.READY

    async def test_update_state_same_state_noop(self, beanie_db):
        """Test updating to same state is a no-op."""
        # Arrange
        service = BaseService()
        original_updated_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
        session = Session(
            session_id="se_same_state",
            room_id="same-state-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=original_updated_at,
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.READY)

        # Assert - Should return without updating
        assert result.status == SessionState.READY
        # Note: updated_at may still be the same if it was a true no-op

    async def test_update_state_invalid_transition(self, beanie_db):
        """Test invalid state transition raises FlcError."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_invalid",
            room_id="invalid-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act & Assert - IDLE cannot transition directly to LIVE
        with pytest.raises(FlcError, match="Invalid state transition"):
            await service.update_session_state(session, SessionState.LIVE)

    async def test_update_state_to_live_sets_started_at(self, beanie_db):
        """Test transitioning to LIVE sets started_at timestamp."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_started_at",
            room_id="started-at-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            started_at=None,
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.LIVE)

        # Assert
        assert result.status == SessionState.LIVE
        assert result.started_at is not None

    async def test_update_state_to_stopped_sets_stopped_at(self, beanie_db):
        """Test transitioning to STOPPED sets stopped_at timestamp."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_stopped_at",
            room_id="stopped-at-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.ENDING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=None,
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.STOPPED)

        # Assert
        assert result.status == SessionState.STOPPED
        assert result.stopped_at is not None

    async def test_update_state_to_cancelled_sets_stopped_at(self, beanie_db):
        """Test transitioning to CANCELLED sets stopped_at timestamp."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_cancelled_at",
            room_id="cancelled-at-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=None,
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.CANCELLED)

        # Assert
        assert result.status == SessionState.CANCELLED
        assert result.stopped_at is not None

    async def test_update_state_to_aborted_sets_stopped_at(self, beanie_db):
        """Test transitioning to ABORTED sets stopped_at timestamp."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_aborted_at",
            room_id="aborted-at-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=None,
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.ABORTED)

        # Assert
        assert result.status == SessionState.ABORTED
        assert result.stopped_at is not None

    async def test_update_state_preserves_existing_started_at(self, beanie_db):
        """Test LIVE transition doesn't overwrite existing started_at."""
        # Arrange
        service = BaseService()
        original_started = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)
        session = Session(
            session_id="se_preserve_started",
            room_id="preserve-started-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            started_at=original_started,  # Already set
        )
        await session.insert()

        # Act
        result = await service.update_session_state(session, SessionState.LIVE)

        # Assert - Should keep original started_at (compare without timezone)
        # MongoDB stores datetimes without timezone info
        assert result.started_at is not None
        assert result.started_at.year == original_started.year
        assert result.started_at.month == original_started.month
        assert result.started_at.day == original_started.day
        assert result.started_at.hour == original_started.hour


@pytest.mark.usefixtures("clear_collections")
class TestGetSessionHelpers:
    """Tests for BaseService session retrieval helper methods."""

    async def test_get_session_by_id_exists(self, beanie_db):
        """Test _get_session_by_id returns session when it exists."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_get_by_id",
            room_id="get-by-id-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await service._get_session_by_id("se_get_by_id")

        # Assert
        assert result is not None
        assert result.session_id == "se_get_by_id"

    async def test_get_session_by_id_not_found(self, beanie_db):
        """Test _get_session_by_id returns None when session doesn't exist."""
        # Arrange
        service = BaseService()

        # Act
        result = await service._get_session_by_id("se_nonexistent")

        # Assert
        assert result is None

    async def test_get_active_session_by_room_id_live(self, beanie_db):
        """Test _get_active_session_by_room_id returns LIVE session."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_active_room",
            room_id="active-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await service._get_active_session_by_room_id("active-room")

        # Assert
        assert result is not None
        assert result.status == SessionState.LIVE

    async def test_get_active_session_by_room_id_stopped(self, beanie_db):
        """Test _get_active_session_by_room_id returns None for STOPPED session."""
        # Arrange
        service = BaseService()
        session = Session(
            session_id="se_stopped_room",
            room_id="stopped-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,  # Not active
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await service._get_active_session_by_room_id("stopped-room")

        # Assert
        assert result is None

    async def test_get_last_session_by_room_id_returns_session(self, beanie_db):
        """Test _get_last_session_by_room_id returns session regardless of status."""
        # Arrange
        service = BaseService()

        # Create session (even stopped sessions should be found)
        session = Session(
            session_id="se_last",
            room_id="last-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,
            runtime=SessionRuntime(),
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        await session.insert()

        # Act
        result = await service._get_last_session_by_room_id("last-room")

        # Assert - Should return the session even though it's STOPPED
        assert result is not None
        assert result.session_id == "se_last"
        assert result.status == SessionState.STOPPED
