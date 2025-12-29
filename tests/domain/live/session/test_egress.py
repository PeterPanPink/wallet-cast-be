"""Tests for EgressOperations domain logic."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.live.session._egress import EgressOperations
from app.schemas import Channel, Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


@dataclass
class MockMuxPlaybackId:
    """Mock Mux playback ID."""

    id: str
    policy: str


@dataclass
class MockMuxStream:
    """Mock Mux stream object."""

    id: str
    stream_key: str
    playback_ids: list = field(default_factory=list)


@dataclass
class MockMuxResponse:
    """Mock Mux API response."""

    data: MockMuxStream


@dataclass
class MockEgressInfo:
    """Mock LiveKit egress info."""

    egress_id: str


@pytest.mark.usefixtures("clear_collections")
class TestStartLive:
    """Tests for EgressOperations.start_live method."""

    async def test_start_live_success(self, beanie_db):
        """Test successful live stream start."""
        # Arrange
        ops = EgressOperations()

        session = Session(
            session_id="se_start_live",
            room_id="start-live-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_mux_stream = MockMuxStream(
            id="mux_stream_123",
            stream_key="stream_key_abc",
            playback_ids=[MockMuxPlaybackId(id="playback_123", policy="public")],
        )
        mock_mux_response = MockMuxResponse(data=mock_mux_stream)
        mock_egress = MockEgressInfo(egress_id="EG_test123")

        # Act
        with (
            patch.object(
                ops.mux,
                "create_live_stream",
                return_value=mock_mux_response,
            ),
            patch.object(
                ops.mux,
                "get_animated_url",
                return_value="https://animated.url",
            ),
            patch.object(
                ops.mux,
                "get_thumbnail_url",
                return_value="https://thumbnail.url",
            ),
            patch.object(
                ops.mux,
                "get_storyboard_url",
                return_value="https://storyboard.url",
            ),
            patch.object(
                ops.livekit,
                "start_room_composite_egress",
                new_callable=AsyncMock,
                return_value=mock_egress,
            ),
            patch("app.domain.live.session._egress.get_app_environ_config") as mock_config,
        ):
            mock_config.return_value.USE_WEB_EGRESS = False
            mock_config.return_value.MUX_RTMP_INGEST_BASE_URL = "rtmps://global-live.mux.com:443"
            mock_config.return_value.MUX_STREAM_BASE_URL = "https://stream.mux.com"
            result = await ops.start_live(room_name="start-live-room")

        # Assert
        assert result.egress_id == "EG_test123"
        assert result.mux_stream_id == "mux_stream_123"
        assert result.mux_stream_key == "stream_key_abc"
        assert result.mux_rtmp_url == "rtmps://global-live.mux.com:443/app"
        assert len(result.mux_playback_ids) == 1
        assert result.mux_playback_ids[0].id == "playback_123"

        # Verify session state updated
        saved = await Session.find_one(Session.session_id == "se_start_live")
        assert saved is not None
        assert saved.status == SessionState.PUBLISHING

    async def test_start_live_room_not_found(self, beanie_db):
        """Test start live fails when room doesn't exist."""
        # Arrange
        ops = EgressOperations()

        # Act & Assert
        with pytest.raises(FlcError) as exc_info:
            await ops.start_live(room_name="nonexistent-room")
        assert exc_info.value.errcode == FlcErrorCode.E_SESSION_NOT_FOUND
        assert exc_info.value.status_code == FlcStatusCode.NOT_FOUND

    async def test_start_live_already_streaming(self, beanie_db):
        """Test start live fails when stream already in progress."""
        # Arrange
        ops = EgressOperations()

        session = Session(
            session_id="se_already_live",
            room_id="already-live-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,  # Already live
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act & Assert
        with pytest.raises(FlcError) as exc_info:
            await ops.start_live(room_name="already-live-room")
        assert exc_info.value.errcode == FlcErrorCode.E_LIVE_STREAM_IN_PROGRESS
        assert exc_info.value.status_code == FlcStatusCode.CONFLICT

    async def test_start_live_publishing_already_streaming(self, beanie_db):
        """Test start live fails when already in PUBLISHING state."""
        # Arrange
        ops = EgressOperations()

        session = Session(
            session_id="se_publishing",
            room_id="publishing-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act & Assert
        with pytest.raises(FlcError) as exc_info:
            await ops.start_live(room_name="publishing-room")
        assert exc_info.value.errcode == FlcErrorCode.E_LIVE_STREAM_IN_PROGRESS
        assert exc_info.value.status_code == FlcStatusCode.CONFLICT


@pytest.mark.usefixtures("clear_collections")
class TestEndLive:
    """Tests for EgressOperations.end_live method."""

    async def test_end_live_success(self, beanie_db):
        """Test successful live stream end."""
        # Arrange
        ops = EgressOperations()

        from app.schemas.session_runtime import LiveKitRuntime, MuxRuntime

        session = Session(
            session_id="se_end_live",
            room_id="end-live-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(
                livekit=LiveKitRuntime(egress_id="EG_end"),
                mux=MuxRuntime(mux_stream_id="mux_end"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        with (
            patch.object(
                ops.livekit,
                "stop_egress",
                new_callable=AsyncMock,
            ) as mock_stop_egress,
            patch.object(
                ops.mux,
                "signal_live_stream_complete",
            ) as mock_signal_complete,
        ):
            await ops.end_live(
                room_name="end-live-room",
                egress_id="EG_end",
                mux_stream_id="mux_end",
            )

            # Assert
            mock_stop_egress.assert_called_once_with("EG_end")
            mock_signal_complete.assert_called_once_with("mux_end")

        # Verify session state updated to ENDING
        saved = await Session.find_one(Session.session_id == "se_end_live")
        assert saved is not None
        assert saved.status == SessionState.ENDING

    async def test_end_live_room_not_found(self, beanie_db):
        """Test end live fails when room doesn't exist."""
        # Arrange
        ops = EgressOperations()

        # Act & Assert
        with pytest.raises(FlcError) as exc_info:
            await ops.end_live(
                room_name="nonexistent-room",
                egress_id="EG_test",
                mux_stream_id="mux_test",
            )
        assert exc_info.value.errcode == FlcErrorCode.E_SESSION_NOT_FOUND
        assert exc_info.value.status_code == FlcStatusCode.NOT_FOUND

    async def test_end_live_egress_already_complete(self, beanie_db):
        """Test end live handles egress already completed gracefully."""
        # Arrange
        ops = EgressOperations()

        session = Session(
            session_id="se_egress_done",
            room_id="egress-done-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act - Simulate egress already complete error
        with (
            patch.object(
                ops.livekit,
                "stop_egress",
                new_callable=AsyncMock,
                side_effect=Exception("EGRESS_COMPLETE"),
            ),
            patch.object(
                ops.mux,
                "signal_live_stream_complete",
            ) as mock_signal,
        ):
            # Should not raise because EGRESS_COMPLETE is handled
            await ops.end_live(
                room_name="egress-done-room",
                egress_id="EG_done",
                mux_stream_id="mux_done",
            )

            # Mux signal should still be called
            mock_signal.assert_called_once()

    async def test_end_live_from_publishing_becomes_cancelled(self, beanie_db):
        """Test ending live from PUBLISHING state transitions through ABORTED to CANCELLED."""
        # Arrange
        ops = EgressOperations()

        # Create channel for recreation

        channel = Channel(
            channel_id="ch_pub_cancel",
            user_id="u.test",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_pub_cancel",
            room_id="pub-cancel-room",
            channel_id="ch_pub_cancel",
            user_id="u.test",
            status=SessionState.PUBLISHING,  # Not yet LIVE
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        with (
            patch.object(
                ops.livekit,
                "stop_egress",
                new_callable=AsyncMock,
            ),
            patch.object(
                ops.mux,
                "signal_live_stream_complete",
            ),
        ):
            await ops.end_live(
                room_name="pub-cancel-room",
                egress_id="EG_pub",
                mux_stream_id="mux_pub",
            )

        # Assert - Should be CANCELLED (via ABORTED) since never went LIVE
        saved = await Session.find_one(Session.session_id == "se_pub_cancel")
        assert saved is not None
        assert saved.status == SessionState.CANCELLED


@pytest.mark.usefixtures("clear_collections")
class TestAbortAndRecreateSession:
    """Tests for EgressOperations._abort_and_recreate_session method.

    This method aborts a session (transitioning to terminal state) and then
    creates a new READY session for the same room_id. The new session is
    fetched via _get_active_session_by_room_id which works correctly since
    the recreated session is in READY state (an active state).
    """

    async def test_abort_already_terminal_creates_new(self, beanie_db):
        """Test recreating session from already terminal state."""
        # Arrange
        ops = EgressOperations()

        channel = Channel(
            channel_id="ch_terminal",
            user_id="u.terminal",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        # Create a STOPPED session (already terminal)
        session = Session(
            session_id="se_terminal",
            room_id="terminal-room",
            channel_id="ch_terminal",
            user_id="u.terminal",
            status=SessionState.STOPPED,  # Already terminal
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act - Method should skip state transitions and create new session
        new_session = await ops._abort_and_recreate_session(session)

        # Assert - New session should be created in READY state
        assert new_session.status == SessionState.READY
        assert new_session.room_id == session.room_id
        assert new_session.channel_id == session.channel_id
        assert new_session.session_id != session.session_id
