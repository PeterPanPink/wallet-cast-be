"""Unit tests for session_ingress router endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from livekit.api import ParticipantInfo, Room

from app.api.v1.dependency import User, get_current_user
from app.api.v1.errors import app_error_handler
from app.api.v1.routers.session_ingress import get_session_service, router
from app.domain.live.session.session_domain import SessionService
from app.domain.live.session.session_models import SessionResponse
from app.schemas.session_state import SessionState
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


@pytest.fixture
def mock_user() -> User:
    """Create a mock authenticated user."""
    return User(user_id="test_user_123")


@pytest.fixture
def mock_session_service() -> AsyncMock:
    """Create a mock SessionService."""
    return AsyncMock(spec=SessionService)


@pytest.fixture
def test_app(
    mock_user: User,
    mock_session_service: AsyncMock,
) -> FastAPI:
    """Create FastAPI test app with dependency overrides."""
    app = FastAPI()

    # Override authentication dependency
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # Override service dependency
    app.dependency_overrides[get_session_service] = lambda: mock_session_service

    # Add exception handler for AppError
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    app.include_router(router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(test_app)


@pytest.fixture
def sample_session() -> SessionResponse:
    """Create a sample SessionResponse for testing."""
    now = datetime.now(timezone.utc)
    return SessionResponse(
        session_id=f"sess_{uuid4().hex[:24]}",
        user_id="test_user_123",
        channel_id="ch_123",
        room_id="room_test_123",
        status=SessionState.IDLE,
        created_at=now,
        updated_at=now,
        max_participants=None,
    )


# ==================== CREATE ROOM TESTS ====================


class TestCreateRoom:
    """Tests for POST /session/ingress/create_room endpoint."""

    def test_create_room_success_with_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully create a room using session_id."""
        # Arrange
        sample_session.status = SessionState.IDLE
        mock_session_service.get_session.return_value = sample_session

        mock_room = MagicMock(spec=Room)
        mock_room.name = "room_test_123"
        mock_room.sid = "RM_test_sid"
        mock_room.metadata = '{"test": "metadata"}'
        mock_session_service.create_room.return_value = mock_room

        payload = {
            "session_id": sample_session.session_id,
            "metadata": '{"test": "metadata"}',
            "empty_timeout": 300,
            "max_participants": 50,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.MAX_PARTICIPANTS_LIMIT = 100
            response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room_name"] == "room_test_123"
        assert data["results"]["room_sid"] == "RM_test_sid"
        assert data["results"]["max_participants"] == 50
        mock_session_service.get_session.assert_called_once_with(
            session_id=sample_session.session_id
        )
        mock_session_service.create_room.assert_called_once()
        mock_session_service.update_session_state.assert_called_once_with(
            session_id=sample_session.session_id,
            new_state=SessionState.READY,
        )

    def test_create_room_success_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully create a room using room_id."""
        # Arrange
        sample_session.status = SessionState.IDLE
        mock_session_service.get_active_session_by_room_id.return_value = sample_session

        mock_room = MagicMock(spec=Room)
        mock_room.name = "room_test_123"
        mock_room.sid = "RM_test_sid"
        mock_room.metadata = None
        mock_session_service.create_room.return_value = mock_room

        payload = {
            "room_id": "room_test_123",
            "max_participants": 100,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.MAX_PARTICIPANTS_LIMIT = 100
            response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room_name"] == "room_test_123"
        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )

    def test_create_room_idempotent_already_ready(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return existing room info when session is already READY."""
        # Arrange
        sample_session.status = SessionState.READY
        mock_session_service.get_session.return_value = sample_session

        mock_room = MagicMock(spec=Room)
        mock_room.name = "room_test_123"
        mock_room.sid = "RM_test_sid"
        mock_room.metadata = None
        mock_session_service.create_room.return_value = mock_room

        payload = {
            "session_id": sample_session.session_id,
            "max_participants": 50,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.MAX_PARTICIPANTS_LIMIT = 100
            response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Should NOT call update_session_state since already READY
        mock_session_service.update_session_state.assert_not_called()

    def test_create_room_max_participants_limit(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should enforce max_participants limit from config."""
        # Arrange
        sample_session.status = SessionState.IDLE
        mock_session_service.get_session.return_value = sample_session

        mock_room = MagicMock(spec=Room)
        mock_room.name = "room_test_123"
        mock_room.sid = "RM_test_sid"
        mock_room.metadata = None
        mock_session_service.create_room.return_value = mock_room

        payload = {
            "session_id": sample_session.session_id,
            "max_participants": 500,  # Requesting more than limit
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.MAX_PARTICIPANTS_LIMIT = 100
            response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["results"]["max_participants"] == 100  # Should be limited

    def test_create_room_forbidden_wrong_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 403 if user doesn't own the session."""
        # Arrange
        sample_session.user_id = "different_user"
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
            "max_participants": 50,
        }

        # Act
        response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_create_room_terminal_state_error(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 400 for terminal state sessions."""
        # Arrange
        sample_session.status = SessionState.STOPPED
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
            "max_participants": 50,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.MAX_PARTICIPANTS_LIMIT = 100
            response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errcode"] == "E_SESSION_TERMINATED"
        assert "terminated" in data["errmesg"].lower()

    def test_create_room_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "session_id": "nonexistent_session",
            "max_participants": 50,
        }

        # Act
        response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errcode"] == "E_SESSION_NOT_FOUND"

    def test_create_room_missing_both_ids(self, client: TestClient):
        """Should return 400 when neither session_id nor room_id provided."""
        # Arrange
        payload = {
            "max_participants": 50,
        }

        # Act
        response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_create_room_both_ids_provided(self, client: TestClient):
        """Should return 400 when both session_id and room_id provided."""
        # Arrange
        payload = {
            "session_id": "sess_123",
            "room_id": "room_123",
            "max_participants": 50,
        }

        # Act
        response = client.post("/session/ingress/create_room", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error


# ==================== DELETE ROOM TESTS ====================


class TestDeleteRoom:
    """Tests for POST /session/ingress/delete_room endpoint."""

    def test_delete_room_success_with_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully delete a room using session_id."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_session_service.delete_room.return_value = None

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        response = client.post("/session/ingress/delete_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room_name"] == sample_session.room_id
        assert data["results"]["deleted"] is True
        mock_session_service.delete_room.assert_called_once_with(room_name=sample_session.room_id)

    def test_delete_room_success_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully delete a room using room_id."""
        # Arrange
        mock_session_service.get_last_session_by_room_id.return_value = sample_session
        mock_session_service.delete_room.return_value = None

        payload = {
            "room_id": "room_test_123",
        }

        # Act
        response = client.post("/session/ingress/delete_room", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_session_service.get_last_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )

    def test_delete_room_forbidden_wrong_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 403 if user doesn't own the session."""
        # Arrange
        sample_session.user_id = "different_user"
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        response = client.post("/session/ingress/delete_room", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_delete_room_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "session_id": "nonexistent_session",
        }

        # Act
        response = client.post("/session/ingress/delete_room", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errcode"] == "E_SESSION_NOT_FOUND"


# ==================== GET HOST TOKEN TESTS ====================


class TestGetHostToken:
    """Tests for POST /session/ingress/get_host_token endpoint."""

    def test_get_host_token_success_with_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully generate host token using session_id."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_session_service.get_host_access_token.return_value = "host_token_abc123"

        payload = {
            "session_id": sample_session.session_id,
            "metadata": '{"role": "host"}',
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_host_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["token"] == "host_token_abc123"
        assert data["results"]["identity"] == "test_user_123"
        assert data["results"]["room_name"] == sample_session.room_id
        assert data["results"]["livekit_url"] == "wss://test.livekit.cloud"
        assert data["results"]["token_ttl"] == 3600
        mock_session_service.get_host_access_token.assert_called_once()

    def test_get_host_token_success_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully generate host token using room_id."""
        # Arrange
        mock_session_service.get_active_session_by_room_id.return_value = sample_session
        mock_session_service.get_host_access_token.return_value = "host_token_abc123"

        payload = {
            "room_id": "room_test_123",
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_host_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )

    def test_get_host_token_forbidden_wrong_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 403 if user doesn't own the session."""
        # Arrange
        sample_session.user_id = "different_user"
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        response = client.post("/session/ingress/get_host_token", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_get_host_token_livekit_url_not_configured(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 500 when LIVEKIT_URL not configured."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_session_service.get_host_access_token.return_value = "host_token_abc123"

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = None
            response = client.post("/session/ingress/get_host_token", json=payload)

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["errcode"] == "E_LIVEKIT_NOT_CONFIGURED"


# ==================== GET GUEST TOKEN TESTS ====================


class TestGetGuestToken:
    """Tests for POST /session/ingress/get_guest_token endpoint."""

    def test_get_guest_token_success_with_can_publish(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully generate guest token with publish permission."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_session_service.get_guest_access_token.return_value = "guest_token_abc123"

        payload = {
            "display_name": "Guest User",
            "session_id": sample_session.session_id,
            "can_publish": True,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_guest_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["token"] == "guest_token_abc123"
        assert data["results"]["identity"].startswith("guest_")  # Identity is auto-generated
        assert data["results"]["room_name"] == sample_session.room_id
        # Verify the service was called with an auto-generated identity
        call_args = mock_session_service.get_guest_access_token.call_args
        assert call_args[1]["identity"].startswith("guest_")
        assert call_args[1]["room_name"] == sample_session.room_id
        assert call_args[1]["display_name"] == "Guest User"
        assert call_args[1]["metadata"] is None
        assert call_args[1]["can_publish"] is True

    def test_get_guest_token_success_view_only(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully generate view-only guest token."""
        # Arrange
        mock_session_service.get_active_session_by_room_id.return_value = sample_session
        mock_session_service.get_guest_access_token.return_value = "guest_token_viewer"

        payload = {
            "display_name": "Viewer",
            "room_id": "room_test_123",
            "can_publish": False,
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_guest_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        # Verify the service was called with an auto-generated identity
        call_args = mock_session_service.get_guest_access_token.call_args
        assert call_args[1]["identity"].startswith("guest_")
        assert call_args[1]["room_name"] == sample_session.room_id
        assert call_args[1]["display_name"] == "Viewer"
        assert call_args[1]["metadata"] is None
        assert call_args[1]["can_publish"] is False

    def test_get_guest_token_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "display_name": "Guest User",
            "session_id": "nonexistent_session",
        }

        # Act
        response = client.post("/session/ingress/get_guest_token", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errcode"] == "E_SESSION_NOT_FOUND"


# ==================== GET RECORDER TOKEN TESTS ====================


class TestGetRecorderToken:
    """Tests for POST /session/ingress/get_recorder_token endpoint."""

    def test_get_recorder_token_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully generate recorder token."""
        # Arrange
        mock_session_service.get_last_session_by_room_id.return_value = sample_session
        mock_session_service.get_recorder_access_token.return_value = "recorder_token_abc123"

        payload = {
            "room_id": "room_test_123",
            "identity": "recorder_001",
            "display_name": "Recorder Bot",
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_recorder_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["token"] == "recorder_token_abc123"
        assert data["results"]["identity"] == "recorder_001"
        mock_session_service.get_recorder_access_token.assert_called_once()

    def test_get_recorder_token_auto_generate_identity(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should auto-generate identity when not provided."""
        # Arrange
        mock_session_service.get_last_session_by_room_id.return_value = sample_session
        mock_session_service.get_recorder_access_token.return_value = "recorder_token_abc123"

        payload = {
            "room_id": "room_test_123",
        }

        # Act
        with patch("app.api.v1.routers.session_ingress.get_app_environ_config") as mock_config:
            mock_config.return_value.LIVEKIT_URL = "wss://test.livekit.cloud"
            response = client.post("/session/ingress/get_recorder_token", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["identity"] == "recorder-room_test_123"


# ==================== UPDATE ROOM METADATA TESTS ====================


class TestUpdateRoomMetadata:
    """Tests for POST /session/ingress/update_room_metadata endpoint."""

    def test_update_room_metadata_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully update room metadata."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        mock_room_info = MagicMock()
        mock_room_info.name = "room_test_123"
        mock_room_info.sid = "RM_test_sid"
        mock_room_info.metadata = '{"theme": "dark"}'
        mock_session_service.update_room_metadata.return_value = mock_room_info

        payload = {
            "session_id": sample_session.session_id,
            "metadata": '{"theme": "dark"}',
        }

        # Act
        response = client.post("/session/ingress/update_room_metadata", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room"] == "room_test_123"
        assert data["results"]["sid"] == "RM_test_sid"
        assert data["results"]["metadata"] == '{"theme": "dark"}'
        mock_session_service.update_room_metadata.assert_called_once_with(
            room_name=sample_session.room_id,
            metadata='{"theme": "dark"}',
        )

    def test_update_room_metadata_forbidden_wrong_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 403 if user doesn't own the session."""
        # Arrange
        sample_session.user_id = "different_user"
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
            "metadata": '{"theme": "dark"}',
        }

        # Act
        response = client.post("/session/ingress/update_room_metadata", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_update_room_metadata_invalid_json(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return 400 for invalid JSON metadata."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_session_service.update_room_metadata.side_effect = AppError(
            errcode=AppErrorCode.E_INVALID_REQUEST,
            errmesg="Invalid JSON",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

        payload = {
            "session_id": sample_session.session_id,
            "metadata": "not valid json",
        }

        # Act
        response = client.post("/session/ingress/update_room_metadata", json=payload)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["errcode"] == "E_INVALID_REQUEST"


# ==================== UPDATE PARTICIPANT NAME TESTS ====================


class TestUpdateParticipantName:
    """Tests for POST /session/ingress/update_participant_name endpoint."""

    def test_update_participant_name_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully update participant name."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        mock_participant = MagicMock(spec=ParticipantInfo)
        mock_participant.identity = "test_user_123"
        mock_participant.name = "New Display Name"
        mock_participant.sid = "PA_test_sid"
        mock_session_service.update_participant.return_value = mock_participant

        payload = {
            "session_id": sample_session.session_id,
            "identity": "test_user_123",  # Same as current user
            "name": "New Display Name",
        }

        # Act
        response = client.post("/session/ingress/update_participant_name", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["identity"] == "test_user_123"
        assert data["results"]["name"] == "New Display Name"
        assert data["results"]["sid"] == "PA_test_sid"
        mock_session_service.update_participant.assert_called_once_with(
            room_name=sample_session.room_id,
            identity="test_user_123",
            name="New Display Name",
        )

    def test_update_participant_name_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully update participant name using room_id."""
        # Arrange
        mock_session_service.get_last_session_by_room_id.return_value = sample_session

        mock_participant = MagicMock(spec=ParticipantInfo)
        mock_participant.identity = "test_user_123"
        mock_participant.name = "Updated Name"
        mock_participant.sid = "PA_test_sid"
        mock_session_service.update_participant.return_value = mock_participant

        payload = {
            "room_id": "room_test_123",
            "identity": "test_user_123",
            "name": "Updated Name",
        }

        # Act
        response = client.post("/session/ingress/update_participant_name", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_session_service.get_last_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )

    def test_update_participant_name_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "session_id": "nonexistent_session",
            "identity": "test_user_123",
            "name": "New Name",
        }

        # Act
        response = client.post("/session/ingress/update_participant_name", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["errcode"] == "E_SESSION_NOT_FOUND"
