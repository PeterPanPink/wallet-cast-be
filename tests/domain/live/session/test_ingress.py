"""Tests for IngressOperations domain logic."""

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.domain.live.session._ingress import IngressOperations
from app.schemas import Session, SessionState
from app.utils.app_errors import AppError, AppErrorCode


@dataclass
class MockRoom:
    """Mock LiveKit Room object."""

    name: str
    sid: str
    metadata: str | None = None
    empty_timeout: int = 300
    max_participants: int = 100


@dataclass
class MockParticipant:
    """Mock LiveKit ParticipantInfo object."""

    identity: str
    name: str
    metadata: str | None = None


class TestCreateRoom:
    """Tests for IngressOperations.create_room method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_create_room_success(self, beanie_db):
        """Test successful LiveKit room creation."""
        # Arrange
        ops = IngressOperations()

        # Create session for the room
        session = Session(
            session_id="se_room_test",
            room_id="test-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_room = MockRoom(name="test-room", sid="RM_abc123")

        # Act
        with patch.object(
            ops.livekit, "create_room", new_callable=AsyncMock, return_value=mock_room
        ) as mock_create:
            result = await ops.create_room(room_name="test-room")

            # Assert
            assert result.name == "test-room"
            assert result.sid == "RM_abc123"
            mock_create.assert_called_once_with(
                room_name="test-room",
                metadata=None,
                empty_timeout=300,
                max_participants=100,
            )

    @pytest.mark.usefixtures("clear_collections")
    async def test_create_room_with_metadata(self, beanie_db):
        """Test room creation with custom metadata."""
        # Arrange
        ops = IngressOperations()
        metadata = '{"layout":"grid"}'

        session = Session(
            session_id="se_meta_room",
            room_id="meta-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.IDLE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_room = MockRoom(name="meta-room", sid="RM_meta", metadata=metadata)

        # Act
        with patch.object(
            ops.livekit, "create_room", new_callable=AsyncMock, return_value=mock_room
        ):
            result = await ops.create_room(
                room_name="meta-room",
                metadata=metadata,
                empty_timeout=600,
                max_participants=50,
            )

            # Assert
            assert result.metadata == metadata


class TestDeleteRoom:
    """Tests for IngressOperations.delete_room method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_delete_room_success(self, beanie_db):
        """Test successful LiveKit room deletion."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_delete",
            room_id="delete-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.STOPPED,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        with patch.object(ops.livekit, "delete_room", new_callable=AsyncMock) as mock_delete:
            await ops.delete_room(room_name="delete-room")

            # Assert
            mock_delete.assert_called_once_with(room_name="delete-room")

    @pytest.mark.usefixtures("clear_collections")
    async def test_delete_room_session_not_found(self, beanie_db):
        """Test delete room fails when session doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.delete_room(room_name="nonexistent-room")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


class TestGetHostAccessToken:
    """Tests for IngressOperations.get_host_access_token method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_host_token_success(self, beanie_db):
        """Test successful host access token generation."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_host_token",
            room_id="host-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.READY,
            max_participants=50,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        expected_token = "jwt.token.host"

        # Act
        with patch.object(
            ops.livekit,
            "create_access_token",
            new_callable=AsyncMock,
            return_value=expected_token,
        ) as mock_token:
            result = await ops.get_host_access_token(
                identity="host-123",
                room_name="host-room",
                display_name="John Host",
                metadata='{"role":"host"}',
            )

            # Assert
            assert result == expected_token
            mock_token.assert_called_once()
            call_kwargs = mock_token.call_args.kwargs
            assert call_kwargs["identity"] == "host-123"
            assert call_kwargs["room"] == "host-room"
            assert call_kwargs["name"] == "John Host"
            assert call_kwargs["room_admin"] is True
            assert call_kwargs["can_publish"] is True

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_host_token_room_not_found(self, beanie_db):
        """Test host token fails when room doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_host_access_token(
                identity="host-123",
                room_name="nonexistent-room",
            )
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


class TestGetGuestAccessToken:
    """Tests for IngressOperations.get_guest_access_token method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_guest_token_viewer_only(self, beanie_db):
        """Test guest token generation for viewer (can_publish=False)."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_guest_viewer",
            room_id="guest-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        expected_token = "jwt.token.guest"

        # Act
        with patch.object(
            ops.livekit,
            "create_access_token",
            new_callable=AsyncMock,
            return_value=expected_token,
        ) as mock_token:
            result = await ops.get_guest_access_token(
                identity="viewer-456",
                room_name="guest-room",
                display_name="Jane Viewer",
                can_publish=False,
            )

            # Assert
            assert result == expected_token
            call_kwargs = mock_token.call_args.kwargs
            assert call_kwargs["identity"] == "viewer-456"
            assert call_kwargs["room_admin"] is False
            assert call_kwargs["can_publish"] is False
            assert call_kwargs["can_subscribe"] is True

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_guest_token_cohost(self, beanie_db):
        """Test guest token generation for co-host (can_publish=True)."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_cohost",
            room_id="cohost-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        expected_token = "jwt.token.cohost"

        # Act
        with patch.object(
            ops.livekit,
            "create_access_token",
            new_callable=AsyncMock,
            return_value=expected_token,
        ) as mock_token:
            result = await ops.get_guest_access_token(
                identity="cohost-789",
                room_name="cohost-room",
                can_publish=True,
            )

            # Assert
            assert result == expected_token
            call_kwargs = mock_token.call_args.kwargs
            assert call_kwargs["can_publish"] is True
            assert call_kwargs["room_admin"] is False

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_guest_token_room_not_found(self, beanie_db):
        """Test guest token fails when room doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_guest_access_token(
                identity="viewer-456",
                room_name="nonexistent-room",
            )
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


class TestGetRecorderAccessToken:
    """Tests for IngressOperations.get_recorder_access_token method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_recorder_token_success(self, beanie_db):
        """Test successful recorder access token generation."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_recorder",
            room_id="recorder-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        expected_token = "jwt.token.recorder"

        # Act
        with patch.object(
            ops.livekit,
            "create_recorder_token",
            return_value=expected_token,
        ) as mock_token:
            result = await ops.get_recorder_access_token(
                room_name="recorder-room",
                identity="recorder-001",
            )

            # Assert
            assert result == expected_token
            mock_token.assert_called_once_with(room="recorder-room")

    @pytest.mark.usefixtures("clear_collections")
    async def test_get_recorder_token_room_not_found(self, beanie_db):
        """Test recorder token fails when room doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.get_recorder_access_token(room_name="nonexistent-room")
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


class TestUpdateRoomMetadata:
    """Tests for IngressOperations.update_room_metadata method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_update_room_metadata_success(self, beanie_db):
        """Test successful room metadata update."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_update_meta",
            room_id="meta-update-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        new_metadata = '{"layout":"grid","theme":"dark"}'
        mock_room = MockRoom(name="meta-update-room", sid="RM_meta", metadata=new_metadata)

        # Act
        with patch.object(
            ops.livekit,
            "update_room_metadata",
            new_callable=AsyncMock,
            return_value=mock_room,
        ) as mock_update:
            result = await ops.update_room_metadata(
                room_name="meta-update-room",
                metadata=new_metadata,
            )

            # Assert
            assert result.metadata == new_metadata
            mock_update.assert_called_once_with(
                room="meta-update-room",
                metadata=new_metadata,
            )

    @pytest.mark.usefixtures("clear_collections")
    async def test_update_room_metadata_room_not_found(self, beanie_db):
        """Test update metadata fails when room doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.update_room_metadata(
                room_name="nonexistent-room",
                metadata='{"test":"data"}',
            )
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND


class TestUpdateParticipant:
    """Tests for IngressOperations.update_participant method."""

    @pytest.mark.usefixtures("clear_collections")
    async def test_update_participant_name(self, beanie_db):
        """Test updating participant display name."""
        # Arrange
        ops = IngressOperations()

        session = Session(
            session_id="se_participant",
            room_id="participant-room",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.LIVE,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        mock_participant = MockParticipant(
            identity="guest-123",
            name="New Name",
        )

        # Act
        with patch.object(
            ops.livekit,
            "update_participant",
            new_callable=AsyncMock,
            return_value=mock_participant,
        ) as mock_update:
            result = await ops.update_participant(
                room_name="participant-room",
                identity="guest-123",
                name="New Name",
            )

            # Assert
            assert result.name == "New Name"
            mock_update.assert_called_once_with(
                room="participant-room",
                identity="guest-123",
                name="New Name",
                metadata=None,
            )

    @pytest.mark.usefixtures("clear_collections")
    async def test_update_participant_room_not_found(self, beanie_db):
        """Test update participant fails when room doesn't exist."""
        # Arrange
        ops = IngressOperations()

        # Act & Assert
        with pytest.raises(AppError) as exc_info:
            await ops.update_participant(
                room_name="nonexistent-room",
                identity="guest-123",
                name="New Name",
            )
        assert exc_info.value.errcode == AppErrorCode.E_SESSION_NOT_FOUND
