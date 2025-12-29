"""Tests for LiveKit host cleanup webhook handlers.

Tests the host cleanup feature:
1. When host leaves, a delayed cleanup task is scheduled
2. When host returns, the cleanup task is cancelled
3. When cleanup runs, session is transitioned to STOPPED
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.webhooks.livekit import handle_participant_joined, handle_participant_left
from app.api.webhooks.schemas.livekit import (
    ParticipantInfo,
    ParticipantJoinedEvent,
    ParticipantLeftEvent,
    Room,
)
from app.schemas import Channel, Session, SessionState
from app.schemas.session_runtime import HostCleanupRuntime, SessionRuntime


def create_participant_left_event(room_name: str, identity: str) -> ParticipantLeftEvent:
    """Create a ParticipantLeftEvent for testing."""
    return ParticipantLeftEvent(
        event="participant_left",
        id="test_event_id",
        createdAt=1234567890,
        room=Room(sid="RM_test", name=room_name),
        participant=ParticipantInfo(
            sid="PA_test",
            identity=identity,
            name="Test User",
            state="ACTIVE",
        ),
    )


def create_participant_joined_event(room_name: str, identity: str) -> ParticipantJoinedEvent:
    """Create a ParticipantJoinedEvent for testing."""
    return ParticipantJoinedEvent(
        event="participant_joined",
        id="test_event_id",
        createdAt=1234567890,
        room=Room(sid="RM_test", name=room_name),
        participant=ParticipantInfo(
            sid="PA_test",
            identity=identity,
            name="Test User",
            state="ACTIVE",
        ),
    )


@pytest.mark.usefixtures("clear_collections")
class TestHandleParticipantLeft:
    """Tests for handle_participant_left webhook handler."""

    async def test_host_leaves_schedules_cleanup_task(self, beanie_db):
        """When host leaves, a delayed cleanup task should be scheduled."""
        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"
        task_id = "test_task_123"

        channel = Channel(
            channel_id="ch_test",
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event
        event = create_participant_left_event(room_name=room_id, identity=user_id)

        # Mock the worker and task
        mock_task = MagicMock()
        mock_task.id = task_id

        mock_enqueue = MagicMock()
        mock_enqueue.start = AsyncMock(return_value=mock_task)

        with patch(
            "app.workers.api_jobs_worker.cleanup_session_after_host_left"
        ) as mock_cleanup_task:
            mock_cleanup_task.enqueue = MagicMock(return_value=mock_enqueue)

            with patch("app.workers.api_jobs_worker.worker") as mock_worker:
                mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
                mock_worker.__aexit__ = AsyncMock(return_value=None)

                # Act
                result = await handle_participant_left(event)

        # Assert
        assert result["handled"] == "participant_left"
        assert result["participant"] == user_id
        assert result["cleanup_task_id"] == task_id

        # Verify session was updated with cleanup task info
        saved_session = await Session.find_one(Session.session_id == session_id)
        assert saved_session is not None
        assert saved_session.runtime.host_cleanup is not None
        assert saved_session.runtime.host_cleanup.task_id == task_id
        assert saved_session.runtime.host_cleanup.host_left_at is not None

    async def test_non_host_leaves_no_cleanup_scheduled(self, beanie_db):
        """When non-host participant leaves, no cleanup task should be scheduled."""
        # Arrange
        host_user_id = "u.host_user"
        viewer_user_id = "u.viewer_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"

        channel = Channel(
            channel_id="ch_test",
            user_id=host_user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=host_user_id,  # Host is different from viewer
            room_id=room_id,
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event for viewer leaving
        event = create_participant_left_event(room_name=room_id, identity=viewer_user_id)

        # Act
        result = await handle_participant_left(event)

        # Assert
        assert result["handled"] == "participant_left"
        assert result["participant"] == viewer_user_id
        assert "cleanup_task_id" not in result

        # Verify session was NOT updated
        saved_session = await Session.find_one(Session.session_id == session_id)
        assert saved_session is not None
        assert saved_session.runtime.host_cleanup is None

    async def test_host_leaves_terminal_state_no_cleanup(self, beanie_db):
        """When host leaves but session is already STOPPED, no cleanup scheduled."""
        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"

        channel = Channel(
            channel_id="ch_test",
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.STOPPED,  # Already terminal
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event
        event = create_participant_left_event(room_name=room_id, identity=user_id)

        # Act
        result = await handle_participant_left(event)

        # Assert
        assert result["handled"] == "participant_left"
        assert "cleanup_task_id" not in result

    async def test_session_not_found_handles_gracefully(self, beanie_db):
        """When session is not found, handler should return gracefully."""
        # Arrange - no session created
        event = create_participant_left_event(room_name="ro_nonexistent", identity="u.some_user")

        # Act
        result = await handle_participant_left(event)

        # Assert
        assert result["handled"] == "participant_left"
        assert result["participant"] == "u.some_user"


@pytest.mark.usefixtures("clear_collections")
class TestHandleParticipantJoined:
    """Tests for handle_participant_joined webhook handler."""

    async def test_host_returns_cancels_cleanup_task(self, beanie_db):
        """When host returns, pending cleanup task should be cancelled."""
        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"
        cleanup_task_id = "cleanup_task_123"

        channel = Channel(
            channel_id="ch_test",
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                host_cleanup=HostCleanupRuntime(
                    task_id=cleanup_task_id,
                    host_left_at=datetime.now(timezone.utc),
                )
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event
        event = create_participant_joined_event(room_name=room_id, identity=user_id)

        # Mock the worker
        with patch("app.workers.api_jobs_worker.worker") as mock_worker:
            mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
            mock_worker.__aexit__ = AsyncMock(return_value=None)
            mock_worker.abort_by_id = AsyncMock(return_value=True)

            # Act
            result = await handle_participant_joined(event)

        # Assert
        assert result["handled"] == "participant_joined"
        assert result["participant"] == user_id
        assert result["cancelled_cleanup_task_id"] == cleanup_task_id

        # Verify abort was called
        mock_worker.abort_by_id.assert_called_once_with(cleanup_task_id, timeout=5)

        # Verify session cleanup was cleared
        saved_session = await Session.find_one(Session.session_id == session_id)
        assert saved_session is not None
        assert saved_session.runtime.host_cleanup is None

    async def test_host_joins_no_pending_cleanup(self, beanie_db):
        """When host joins but no cleanup is pending, just handle normally."""
        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"

        channel = Channel(
            channel_id="ch_test",
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),  # No host_cleanup
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event
        event = create_participant_joined_event(room_name=room_id, identity=user_id)

        # Act
        result = await handle_participant_joined(event)

        # Assert
        assert result["handled"] == "participant_joined"
        assert result["participant"] == user_id
        assert "cancelled_cleanup_task_id" not in result

    async def test_non_host_joins_no_cleanup_cancelled(self, beanie_db):
        """When non-host joins with pending cleanup, cleanup should NOT be cancelled."""
        # Arrange
        host_user_id = "u.host_user"
        viewer_user_id = "u.viewer_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"
        cleanup_task_id = "cleanup_task_123"

        channel = Channel(
            channel_id="ch_test",
            user_id=host_user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=host_user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                host_cleanup=HostCleanupRuntime(
                    task_id=cleanup_task_id,
                    host_left_at=datetime.now(timezone.utc),
                )
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event for viewer joining
        event = create_participant_joined_event(room_name=room_id, identity=viewer_user_id)

        # Act
        result = await handle_participant_joined(event)

        # Assert
        assert result["handled"] == "participant_joined"
        assert result["participant"] == viewer_user_id
        assert "cancelled_cleanup_task_id" not in result

        # Verify cleanup task info is still there
        saved_session = await Session.find_one(Session.session_id == session_id)
        assert saved_session is not None
        assert saved_session.runtime.host_cleanup is not None
        assert saved_session.runtime.host_cleanup.task_id == cleanup_task_id

    async def test_host_joins_idle_session_transitions_to_ready(self, beanie_db):
        """When host joins an IDLE session, it should transition to READY."""
        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"

        channel = Channel(
            channel_id="ch_test",
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id=session_id,
            channel_id="ch_test",
            user_id=user_id,
            room_id=room_id,
            title="Test Session",
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Create event
        event = create_participant_joined_event(room_name=room_id, identity=user_id)

        # Act
        result = await handle_participant_joined(event)

        # Assert
        assert result["handled"] == "participant_joined"

        # Verify session was transitioned to READY
        saved_session = await Session.find_one(Session.session_id == session_id)
        assert saved_session is not None
        assert saved_session.status == SessionState.READY


@pytest.mark.usefixtures("clear_collections")
class TestHostCleanupRuntime:
    """Tests for HostCleanupRuntime model."""

    def test_host_cleanup_runtime_defaults(self):
        """Test HostCleanupRuntime has correct defaults."""
        runtime = HostCleanupRuntime()
        assert runtime.task_id is None
        assert runtime.host_left_at is None

    def test_host_cleanup_runtime_with_values(self):
        """Test HostCleanupRuntime with values."""
        now = datetime.now(timezone.utc)
        runtime = HostCleanupRuntime(
            task_id="task_123",
            host_left_at=now,
        )
        assert runtime.task_id == "task_123"
        assert runtime.host_left_at == now

    def test_session_runtime_includes_host_cleanup(self):
        """Test SessionRuntime includes host_cleanup field."""
        runtime = SessionRuntime(
            host_cleanup=HostCleanupRuntime(
                task_id="task_123",
                host_left_at=datetime.now(timezone.utc),
            )
        )
        assert runtime.host_cleanup is not None
        assert runtime.host_cleanup.task_id == "task_123"
