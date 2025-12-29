"""Tests for SessionOperations domain logic."""

from datetime import datetime, timezone

import pytest

from app.domain.live.session._sessions import SessionOperations
from app.domain.live.session.session_models import (
    SessionCreateParams,
    SessionResponse,
    SessionUpdateParams,
)
from app.schemas import Channel, Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.app_errors import AppError, AppErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestCreateSession:
    """Tests for SessionOperations.create_session method."""

    async def test_create_session_success(self, beanie_db):
        """Test successful session creation with valid channel."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_test_create"
        user_id = "u.test_user"

        # Create channel first
        channel = Channel(
            channel_id=channel_id,
            user_id=user_id,
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id=user_id,
            title="Test Session",
        )

        # Act
        result = await ops.create_session(params)

        # Assert
        assert result is not None
        assert isinstance(result, SessionResponse)
        assert result.channel_id == channel_id
        assert result.user_id == user_id
        assert result.title == "Test Session"
        assert result.status == SessionState.IDLE
        assert result.session_id.startswith("se_")
        assert result.room_id.startswith("ro_")

        # Verify DB state
        saved = await Session.find_one(Session.session_id == result.session_id)
        assert saved is not None
        assert saved.status == SessionState.IDLE

    async def test_create_session_inherits_channel_defaults(self, beanie_db):
        """Test session inherits title/description/lang from channel if not provided."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_inherit"
        user_id = "u.inherit_user"

        channel = Channel(
            channel_id=channel_id,
            user_id=user_id,
            title="Channel Title",
            description="Channel Description",
            lang="en",
            location="US",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id=user_id,
            # Not providing title/description - should inherit from channel
        )

        # Act
        result = await ops.create_session(params)

        # Assert - Should inherit from channel
        assert result.title == "Channel Title"
        assert result.description == "Channel Description"
        assert result.lang == "en"
        assert result.location == "US"

    async def test_create_session_overrides_channel_defaults(self, beanie_db):
        """Test session params override channel defaults when provided."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_override"
        user_id = "u.override_user"

        channel = Channel(
            channel_id=channel_id,
            user_id=user_id,
            title="Channel Title",
            description="Channel Description",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id=user_id,
            title="Session Title",
            description="Session Description",
        )

        # Act
        result = await ops.create_session(params)

        # Assert - Should use session params
        assert result.title == "Session Title"
        assert result.description == "Session Description"

    async def test_create_session_channel_not_found(self, beanie_db):
        """Test create session fails when channel doesn't exist."""
        # Arrange
        ops = SessionOperations()
        params = SessionCreateParams(
            channel_id="ch_nonexistent",
            user_id="u.test_user",
        )

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.create_session(params)
        assert exc_info.value.errcode == AppErrorCode.E_CHANNEL_NOT_FOUND

    async def test_create_session_user_mismatch(self, beanie_db):
        """Test create session fails when user_id doesn't match channel owner."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_mismatch"

        channel = Channel(
            channel_id=channel_id,
            user_id="u.owner",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id="u.different_user",
        )

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.create_session(params)
        assert exc_info.value.errcode == AppErrorCode.E_CHANNEL_NOT_FOUND

    async def test_create_session_active_session_exists(self, beanie_db):
        """Test create session fails when active session already exists for channel."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_active"
        user_id = "u.active_user"

        channel = Channel(
            channel_id=channel_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        # Create existing active session
        existing = Session(
            session_id="se_existing",
            room_id="ro_existing",
            channel_id=channel_id,
            user_id=user_id,
            status=SessionState.READY,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await existing.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id=user_id,
        )

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.create_session(params)
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_EXISTS

    async def test_create_session_end_existing_flag(self, beanie_db):
        """Test create session with end_existing=True ends existing session."""
        # Arrange
        ops = SessionOperations()
        channel_id = "ch_end_existing"
        user_id = "u.end_existing_user"

        channel = Channel(
            channel_id=channel_id,
            user_id=user_id,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        # Create existing IDLE session
        existing = Session(
            session_id="se_to_end",
            room_id="ro_to_end",
            channel_id=channel_id,
            user_id=user_id,
            status=SessionState.IDLE,
            runtime=SessionRuntime(),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await existing.insert()

        params = SessionCreateParams(
            channel_id=channel_id,
            user_id=user_id,
            end_existing=True,
        )

        # Act
        result = await ops.create_session(params)

        # Assert - New session created
        assert result.session_id != "se_to_end"
        assert result.status == SessionState.IDLE

        # Old session should be cancelled
        old = await Session.find_one(Session.session_id == "se_to_end")
        assert old is not None
        assert old.status == SessionState.CANCELLED


@pytest.mark.usefixtures("clear_collections")
class TestGetSession:
    """Tests for SessionOperations.get_session method."""

    async def test_get_session_success(self, beanie_db):
        """Test getting an existing session by ID."""
        # Arrange
        ops = SessionOperations()
        session = Session(
            session_id="se_get_test",
            room_id="ro_get_test",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            title="Test Session",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.get_session("se_get_test")

        # Assert
        assert result.session_id == "se_get_test"
        assert result.room_id == "ro_get_test"
        assert result.title == "Test Session"
        assert result.status == SessionState.READY

    async def test_get_session_not_found(self, beanie_db):
        """Test getting a non-existent session raises AppError."""
        # Arrange
        ops = SessionOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_session("se_nonexistent")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


@pytest.mark.usefixtures("clear_collections")
class TestGetActiveSessionByRoomId:
    """Tests for SessionOperations.get_active_session_by_room_id method."""

    async def test_get_active_session_success(self, beanie_db):
        """Test getting an active session by room ID."""
        # Arrange
        ops = SessionOperations()
        session = Session(
            session_id="se_active",
            room_id="ro_active_room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.get_active_session_by_room_id("ro_active_room")

        # Assert
        assert result.room_id == "ro_active_room"
        assert result.status == SessionState.LIVE

    async def test_get_active_session_not_found_stopped(self, beanie_db):
        """Test getting active session fails for stopped session."""
        # Arrange
        ops = SessionOperations()
        session = Session(
            session_id="se_stopped",
            room_id="ro_stopped_room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,  # Not active
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_active_session_by_room_id("ro_stopped_room")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND

    async def test_get_active_session_not_found_no_room(self, beanie_db):
        """Test getting active session fails when room doesn't exist."""
        # Arrange
        ops = SessionOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_active_session_by_room_id("ro_nonexistent")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


@pytest.mark.usefixtures("clear_collections")
class TestGetLastSessionByRoomId:
    """Tests for SessionOperations.get_last_session_by_room_id method."""

    async def test_get_last_session_returns_session(self, beanie_db):
        """Test getting a session by room_id regardless of status."""
        # Arrange
        ops = SessionOperations()
        now = datetime.now(timezone.utc)

        # Create a stopped session
        session = Session(
            session_id="se_last",
            room_id="ro_last_room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,
            created_at=now,
            updated_at=now,
        )
        await session.insert()

        # Act
        result = await ops.get_last_session_by_room_id("ro_last_room")

        # Assert - Should return the session even though it's STOPPED
        assert result.session_id == "se_last"
        assert result.status == SessionState.STOPPED

    async def test_get_last_session_not_found(self, beanie_db):
        """Test getting last session when no sessions exist for room."""
        # Arrange
        ops = SessionOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_last_session_by_room_id("ro_nonexistent")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


@pytest.mark.usefixtures("clear_collections")
class TestGetActiveSessionByChannel:
    """Tests for SessionOperations.get_active_session_by_channel method."""

    async def test_get_active_session_by_channel_success(self, beanie_db):
        """Test getting active session for a channel."""
        # Arrange
        ops = SessionOperations()
        session = Session(
            session_id="se_ch_active",
            room_id="ro_ch_active",
            channel_id="ch_find_active",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.get_active_session_by_channel("ch_find_active")

        # Assert
        assert result.channel_id == "ch_find_active"
        assert result.status == SessionState.LIVE

    async def test_get_active_session_by_channel_not_found(self, beanie_db):
        """Test getting active session when no active session for channel."""
        # Arrange
        ops = SessionOperations()

        # Create stopped session
        session = Session(
            session_id="se_stopped_ch",
            room_id="ro_stopped_ch",
            channel_id="ch_stopped",
            user_id="u.test",
            status=SessionState.STOPPED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_active_session_by_channel("ch_stopped")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


@pytest.mark.usefixtures("clear_collections")
class TestListSessions:
    """Tests for SessionOperations.list_sessions method."""

    async def test_list_sessions_empty(self, beanie_db):
        """Test listing sessions when none exist."""
        # Arrange
        ops = SessionOperations()

        # Act
        result = await ops.list_sessions()

        # Assert
        assert result.sessions == []
        assert result.next_cursor is None

    async def test_list_sessions_basic(self, beanie_db):
        """Test listing sessions returns all sessions."""
        # Arrange
        ops = SessionOperations()
        for i in range(3):
            session = Session(
                session_id=f"se_list_{i}",
                room_id=f"ro_list_{i}",
                channel_id=f"ch_list_{i}",  # Different channel per session
                user_id="u.list",
                status=SessionState.STOPPED,  # Use terminal state to avoid unique index
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await session.insert()

        # Act
        result = await ops.list_sessions()

        # Assert
        assert len(result.sessions) == 3

    async def test_list_sessions_filter_by_channel(self, beanie_db):
        """Test listing sessions filtered by channel_id."""
        # Arrange
        ops = SessionOperations()

        # Channel 1 sessions (use STOPPED to allow multiple per channel)
        for i in range(2):
            session = Session(
                session_id=f"se_ch1_{i}",
                room_id=f"ro_ch1_{i}",
                channel_id="ch_filter_1",
                user_id="u.test",
                status=SessionState.STOPPED,  # Terminal state
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await session.insert()

        # Channel 2 session
        session = Session(
            session_id="se_ch2_0",
            room_id="ro_ch2_0",
            channel_id="ch_filter_2",
            user_id="u.test",
            status=SessionState.STOPPED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        result = await ops.list_sessions(channel_id="ch_filter_1")

        # Assert
        assert len(result.sessions) == 2
        assert all(s.channel_id == "ch_filter_1" for s in result.sessions)

    async def test_list_sessions_filter_by_status(self, beanie_db):
        """Test listing sessions filtered by status."""
        # Arrange
        ops = SessionOperations()

        # Create sessions with different statuses and different channels
        for i, status in enumerate([SessionState.IDLE, SessionState.READY, SessionState.LIVE]):
            session = Session(
                session_id=f"se_status_{status.value}",
                room_id=f"ro_status_{status.value}",
                channel_id=f"ch_status_{i}",  # Different channel per session
                user_id="u.test",
                status=status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await session.insert()

        # Act - Filter by LIVE status
        result = await ops.list_sessions(status=SessionState.LIVE)

        # Assert
        assert len(result.sessions) == 1
        assert result.sessions[0].status == SessionState.LIVE

    async def test_list_sessions_filter_by_multiple_statuses(self, beanie_db):
        """Test listing sessions filtered by multiple statuses."""
        # Arrange
        ops = SessionOperations()

        for i, status in enumerate([SessionState.IDLE, SessionState.READY, SessionState.STOPPED]):
            session = Session(
                session_id=f"se_multi_{status.value}",
                room_id=f"ro_multi_{status.value}",
                channel_id=f"ch_multi_{i}",  # Different channel per session
                user_id="u.test",
                status=status,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            await session.insert()

        # Act - Filter by IDLE and READY
        result = await ops.list_sessions(status=[SessionState.IDLE, SessionState.READY])

        # Assert
        assert len(result.sessions) == 2
        statuses = {s.status for s in result.sessions}
        assert statuses == {SessionState.IDLE, SessionState.READY}

    async def test_list_sessions_datetime_serialization(self, beanie_db):
        """Test that datetime fields are correctly serialized/deserialized.

        This test ensures the Beanie query pattern correctly handles datetime
        fields without ValidationError from MongoDB's extended JSON format.
        """
        # Arrange
        ops = SessionOperations()
        now = datetime.now(timezone.utc)

        # Create session with explicit datetime fields
        session = Session(
            session_id="se_datetime_test",
            room_id="ro_datetime_test",
            channel_id="ch_datetime_test",
            user_id="u.datetime_test",
            status=SessionState.LIVE,
            created_at=now,
            updated_at=now,
            started_at=now,
        )
        await session.insert()

        # Act - List sessions (this should not raise ValidationError)
        result = await ops.list_sessions()

        # Assert
        assert len(result.sessions) == 1
        s = result.sessions[0]
        assert s.session_id == "se_datetime_test"
        # Verify datetime fields are properly parsed
        assert isinstance(s.created_at, datetime)
        assert isinstance(s.updated_at, datetime)
        assert isinstance(s.started_at, datetime)

    async def test_list_sessions_pagination_with_cursor(self, beanie_db):
        """Test pagination cursor correctly handles datetime comparison."""
        # Arrange
        ops = SessionOperations()
        from datetime import timedelta

        base_time = datetime.now(timezone.utc)

        # Create 5 sessions with different timestamps
        for i in range(5):
            session = Session(
                session_id=f"se_page_{i}",
                room_id=f"ro_page_{i}",
                channel_id=f"ch_page_{i}",
                user_id="u.page_test",
                status=SessionState.STOPPED,
                created_at=base_time - timedelta(minutes=i),
                updated_at=base_time - timedelta(minutes=i),
            )
            await session.insert()

        # Act - Get first page
        page1 = await ops.list_sessions(page_size=2)

        # Assert - First page
        assert len(page1.sessions) == 2
        assert page1.next_cursor is not None
        # Sessions should be ordered by created_at DESC
        assert page1.sessions[0].session_id == "se_page_0"
        assert page1.sessions[1].session_id == "se_page_1"

        # Act - Get second page using cursor
        page2 = await ops.list_sessions(page_size=2, cursor=page1.next_cursor)

        # Assert - Second page
        assert len(page2.sessions) == 2
        assert page2.next_cursor is not None
        assert page2.sessions[0].session_id == "se_page_2"
        assert page2.sessions[1].session_id == "se_page_3"

        # Act - Get third page
        page3 = await ops.list_sessions(page_size=2, cursor=page2.next_cursor)

        # Assert - Third page (last session)
        assert len(page3.sessions) == 1
        assert page3.next_cursor is None
        assert page3.sessions[0].session_id == "se_page_4"

    async def test_list_sessions_combined_filters_with_datetime(self, beanie_db):
        """Test multiple filters combined work with datetime fields."""
        # Arrange
        ops = SessionOperations()
        now = datetime.now(timezone.utc)

        # Create sessions with different attributes
        # Note: Only one active (non-terminal) session per channel due to unique index
        sessions_data = [
            ("se_combo_1", "ch_combo_1", "u.alice", SessionState.LIVE),
            ("se_combo_2", "ch_combo_2", "u.bob", SessionState.LIVE),
            ("se_combo_3", "ch_combo_3", "u.alice", SessionState.STOPPED),
            ("se_combo_4", "ch_combo_4", "u.alice", SessionState.STOPPED),
        ]

        for i, (sid, ch, uid, status) in enumerate(sessions_data):
            session = Session(
                session_id=sid,
                room_id=f"ro_combo_{i}",
                channel_id=ch,
                user_id=uid,
                status=status,
                created_at=now,
                updated_at=now,
                started_at=now if status == SessionState.LIVE else None,
            )
            await session.insert()

        # Act - Filter by user_id
        result = await ops.list_sessions(user_id="u.alice")

        # Assert - Should return 3 sessions for alice
        assert len(result.sessions) == 3
        assert all(s.user_id == "u.alice" for s in result.sessions)

        # Act - Filter by user_id and status
        result2 = await ops.list_sessions(user_id="u.alice", status=SessionState.LIVE)

        # Assert
        assert len(result2.sessions) == 1
        assert result2.sessions[0].session_id == "se_combo_1"

        # Act - Filter by user_id and multiple statuses
        result3 = await ops.list_sessions(
            user_id="u.alice", status=[SessionState.LIVE, SessionState.STOPPED]
        )

        # Assert - All alice's sessions match these statuses
        assert len(result3.sessions) == 3

    async def test_list_sessions_filter_by_user_id(self, beanie_db):
        """Test listing sessions filtered by user_id."""
        # Arrange
        ops = SessionOperations()
        now = datetime.now(timezone.utc)

        # Create sessions for different users
        for i, user_id in enumerate(["u.user_a", "u.user_a", "u.user_b"]):
            session = Session(
                session_id=f"se_user_{i}",
                room_id=f"ro_user_{i}",
                channel_id=f"ch_user_{i}",
                user_id=user_id,
                status=SessionState.STOPPED,
                created_at=now,
                updated_at=now,
            )
            await session.insert()

        # Act
        result = await ops.list_sessions(user_id="u.user_a")

        # Assert
        assert len(result.sessions) == 2
        assert all(s.user_id == "u.user_a" for s in result.sessions)


@pytest.mark.usefixtures("clear_collections")
class TestUpdateSession:
    """Tests for SessionOperations.update_session method."""

    async def test_update_session_title(self, beanie_db):
        """Test updating session title."""
        # Arrange
        ops = SessionOperations()
        session = Session(
            session_id="se_update",
            room_id="ro_update",
            channel_id="ch_update",
            user_id="u.update",
            title="Old Title",
            status=SessionState.READY,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        params = SessionUpdateParams(title="New Title")

        # Act
        result = await ops.update_session("se_update", params)

        # Assert
        assert result.title == "New Title"

        # Verify DB state
        saved = await Session.find_one(Session.session_id == "se_update")
        assert saved is not None
        assert saved.title == "New Title"

    async def test_update_session_not_found(self, beanie_db):
        """Test updating non-existent session raises AppError."""
        # Arrange
        ops = SessionOperations()
        params = SessionUpdateParams(title="New Title")

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.update_session("se_nonexistent", params)
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND
