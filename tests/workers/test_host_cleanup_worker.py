"""Tests for host cleanup worker task."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.schemas import Channel, Session, SessionState
from app.schemas.session_runtime import (
    HostCleanupRuntime,
    LiveKitRuntime,
    MuxRuntime,
    SessionRuntime,
)
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


def create_mock_task_context(task_id: str) -> MagicMock:
    """Create a mock TaskContext with the given task_id."""
    mock_context = MagicMock()
    mock_context.task_id = task_id
    return mock_context


@pytest.mark.usefixtures("clear_collections")
class TestCleanupSessionAfterHostLeft:
    """Tests for cleanup_session_after_host_left worker task."""

    async def test_cleanup_session_success(self, beanie_db):
        """Test successful cleanup when host is still absent."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"
        task_id = "test_task_123"
        egress_id = "EG_test_egress"
        mux_stream_id = "mux_test_stream"

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
                livekit=LiveKitRuntime(egress_id=egress_id),
                mux=MuxRuntime(mux_stream_id=mux_stream_id),
                host_cleanup=HostCleanupRuntime(
                    task_id=task_id,
                    host_left_at=datetime.now(timezone.utc),
                ),
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Mock services
        mock_livekit = MagicMock()
        mock_livekit.stop_egress = AsyncMock()

        mock_mux = MagicMock()
        mock_mux.signal_live_stream_complete = MagicMock()

        mock_service = MagicMock()
        mock_service.delete_room = AsyncMock()
        mock_service.update_session_state = AsyncMock()

        # Set up context var with matching task_id
        mock_context = create_mock_task_context(task_id)
        token = worker._task_context.set(mock_context)

        try:
            with (
                patch("app.services.integrations.livekit_service.livekit_service", mock_livekit),
                patch("app.services.integrations.mux_service.mux_service", mock_mux),
                patch(
                    "app.domain.live.session.session_domain.SessionService",
                    return_value=mock_service,
                ),
            ):
                # Act - call the underlying function directly via .fn
                result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert
        assert result["status"] == "completed"
        assert result["session_id"] == session_id

        # Verify egress was stopped
        mock_livekit.stop_egress.assert_called_once_with(egress_id)

        # Verify Mux was signaled
        mock_mux.signal_live_stream_complete.assert_called_once_with(mux_stream_id)

        # Verify room was deleted
        mock_service.delete_room.assert_called_once_with(room_name=room_id)

        # Verify state transitions were called
        assert mock_service.update_session_state.call_count == 2

    async def test_cleanup_skipped_session_not_found(self, beanie_db):
        """Test cleanup is skipped when session doesn't exist."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left

        # Act - no session exists, call underlying function directly
        result = await cleanup_session_after_host_left.fn("se_nonexistent")

        # Assert
        assert result["status"] == "skipped"
        assert result["reason"] == "session_not_found"

    async def test_cleanup_skipped_already_terminal(self, beanie_db):
        """Test cleanup is skipped when session is already in terminal state."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left

        # Arrange
        user_id = "u.host_user"
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
            room_id="ro_test",
            title="Test Session",
            status=SessionState.STOPPED,  # Already terminal
            runtime=SessionRuntime(),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act - call the underlying function directly via .fn
        result = await cleanup_session_after_host_left.fn(session_id)

        # Assert
        assert result["status"] == "skipped"
        assert result["reason"] == "already_terminal"

    async def test_cleanup_skipped_task_id_mismatch(self, beanie_db):
        """Test cleanup is skipped when task ID doesn't match (host returned)."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

        # Arrange
        user_id = "u.host_user"
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
            room_id="ro_test",
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                host_cleanup=HostCleanupRuntime(
                    task_id="old_task_123",  # Different from current task
                    host_left_at=datetime.now(timezone.utc),
                ),
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Set up context var with different task_id
        mock_context = create_mock_task_context("new_task_456")
        token = worker._task_context.set(mock_context)

        try:
            # Act - call the underlying function directly via .fn
            result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert
        assert result["status"] == "skipped"
        assert result["reason"] == "task_id_mismatch"

    async def test_cleanup_skipped_no_host_cleanup_info(self, beanie_db):
        """Test cleanup is skipped when host_cleanup is None."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

        # Arrange
        user_id = "u.host_user"
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
            room_id="ro_test",
            title="Test Session",
            status=SessionState.LIVE,
            runtime=SessionRuntime(host_cleanup=None),  # No cleanup info
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Set up context var
        mock_context = create_mock_task_context("some_task")
        token = worker._task_context.set(mock_context)

        try:
            # Act - call the underlying function directly via .fn
            result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert
        assert result["status"] == "skipped"
        assert result["reason"] == "task_id_mismatch"

    async def test_cleanup_handles_egress_already_completed(self, beanie_db):
        """Test cleanup handles egress already completed gracefully."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

        # Arrange
        user_id = "u.host_user"
        room_id = "ro_test_room"
        session_id = "se_test_session"
        task_id = "test_task_123"
        egress_id = "EG_test_egress"

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
                livekit=LiveKitRuntime(egress_id=egress_id),
                host_cleanup=HostCleanupRuntime(
                    task_id=task_id,
                    host_left_at=datetime.now(timezone.utc),
                ),
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Mock livekit_service to simulate egress already completed error
        mock_livekit = MagicMock()
        mock_livekit.stop_egress = AsyncMock(
            side_effect=Exception("EGRESS_COMPLETE: egress already completed")
        )

        mock_mux = MagicMock()

        mock_service = MagicMock()
        mock_service.delete_room = AsyncMock()
        mock_service.update_session_state = AsyncMock()

        # Set up context var with matching task_id
        mock_context = create_mock_task_context(task_id)
        token = worker._task_context.set(mock_context)

        try:
            with (
                patch("app.services.integrations.livekit_service.livekit_service", mock_livekit),
                patch("app.services.integrations.mux_service.mux_service", mock_mux),
                patch(
                    "app.domain.live.session.session_domain.SessionService",
                    return_value=mock_service,
                ),
            ):
                # Act - should not raise, call underlying function directly via .fn
                result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert - cleanup should still complete
        assert result["status"] == "completed"

    async def test_cleanup_handles_room_already_deleted(self, beanie_db):
        """Test cleanup handles room already deleted gracefully."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

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
            runtime=SessionRuntime(
                host_cleanup=HostCleanupRuntime(
                    task_id=task_id,
                    host_left_at=datetime.now(timezone.utc),
                ),
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_livekit = MagicMock()
        mock_mux = MagicMock()

        # Simulate room already deleted
        mock_service = MagicMock()
        mock_service.delete_room = AsyncMock(
            side_effect=AppError(
                errcode=AppErrorCode.E_SESSION_NOT_FOUND,
                errmesg="Room not found",
                status_code=HttpStatusCode.NOT_FOUND,
            )
        )
        mock_service.update_session_state = AsyncMock()

        # Set up context var with matching task_id
        mock_context = create_mock_task_context(task_id)
        token = worker._task_context.set(mock_context)

        try:
            with (
                patch("app.services.integrations.livekit_service.livekit_service", mock_livekit),
                patch("app.services.integrations.mux_service.mux_service", mock_mux),
                patch(
                    "app.domain.live.session.session_domain.SessionService",
                    return_value=mock_service,
                ),
            ):
                # Act - should not raise, call underlying function directly via .fn
                result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert - cleanup should still complete
        assert result["status"] == "completed"

    async def test_cleanup_without_egress_or_mux(self, beanie_db):
        """Test cleanup works when there's no egress or mux stream."""
        from app.workers.api_jobs_worker import cleanup_session_after_host_left, worker

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
            status=SessionState.READY,  # Not LIVE, no egress
            runtime=SessionRuntime(
                # No livekit or mux runtime
                host_cleanup=HostCleanupRuntime(
                    task_id=task_id,
                    host_left_at=datetime.now(timezone.utc),
                ),
            ),
            version=1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_livekit = MagicMock()
        mock_mux = MagicMock()

        mock_service = MagicMock()
        mock_service.delete_room = AsyncMock()
        mock_service.update_session_state = AsyncMock()

        # Set up context var with matching task_id
        mock_context = create_mock_task_context(task_id)
        token = worker._task_context.set(mock_context)

        try:
            with (
                patch("app.services.integrations.livekit_service.livekit_service", mock_livekit),
                patch("app.services.integrations.mux_service.mux_service", mock_mux),
                patch(
                    "app.domain.live.session.session_domain.SessionService",
                    return_value=mock_service,
                ),
            ):
                # Act - call the underlying function directly via .fn
                result = await cleanup_session_after_host_left.fn(session_id)
        finally:
            worker._task_context.reset(token)

        # Assert
        assert result["status"] == "completed"

        # Verify egress and mux were NOT called (no IDs)
        mock_livekit.stop_egress.assert_not_called()
        mock_mux.signal_live_stream_complete.assert_not_called()

        # Verify room was still deleted
        mock_service.delete_room.assert_called_once()
