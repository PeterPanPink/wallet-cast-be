"""Unit tests for session_ingress_caption router endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from streaq import Worker

from app.api.v1.dependency import User, get_current_user
from app.api.v1.errors import app_error_handler
from app.api.v1.routers.session_ingress_caption import (
    get_caption_worker,
    get_session_service,
    router,
)
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
def mock_caption_worker() -> MagicMock:
    """Create a mock streaq Worker for caption agent."""
    mock_worker = MagicMock(spec=Worker)
    mock_worker.__aenter__ = AsyncMock(return_value=mock_worker)
    mock_worker.__aexit__ = AsyncMock(return_value=None)
    return mock_worker


@pytest.fixture
def test_app(
    mock_user: User,
    mock_session_service: AsyncMock,
    mock_caption_worker: MagicMock,
) -> FastAPI:
    """Create FastAPI test app with dependency overrides."""
    app = FastAPI()

    # Override authentication dependency
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # Override service dependency
    app.dependency_overrides[get_session_service] = lambda: mock_session_service

    # Override caption worker dependency
    app.dependency_overrides[get_caption_worker] = lambda: mock_caption_worker

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
    """Create a sample session for testing."""
    now = datetime.now(timezone.utc)
    return SessionResponse(
        session_id="sess_test_123",
        room_id="room_test_123",
        channel_id="chan_test_123",
        user_id="test_user_123",
        status=SessionState.READY,
        created_at=now,
        updated_at=now,
        max_participants=10,
    )


# ==================== ENABLE CAPTION TESTS ====================


class TestEnableCaption:
    """Tests for POST /session/ingress/caption/enable endpoint."""

    def test_enable_caption_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_caption_worker: MagicMock,
        sample_session: SessionResponse,
    ):
        """Should successfully enable captions."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_task = MagicMock()
        mock_task.id = "test_job_123"
        with patch("app.api.v1.routers.session_ingress_caption.start_caption_agent") as mock_start:
            mock_start.enqueue = AsyncMock(return_value=mock_task)

            payload = {
                "session_id": sample_session.session_id,
                "translation_languages": ["Spanish", "French"],
            }

            # Act
            response = client.post("/session/ingress/enable_caption", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == sample_session.session_id
        assert data["results"]["status"] == "starting"
        assert data["results"]["job_id"] == "test_job_123"

    def test_enable_caption_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_caption_worker: MagicMock,
        sample_session: SessionResponse,
    ):
        """Should successfully enable captions using room_id."""
        # Arrange
        mock_session_service.get_active_session_by_room_id.return_value = sample_session
        mock_task = MagicMock()
        mock_task.id = "test_job_123"
        with patch("app.api.v1.routers.session_ingress_caption.start_caption_agent") as mock_start:
            mock_start.enqueue = AsyncMock(return_value=mock_task)

            payload = {
                "room_id": "room_test_123",
            }

            # Act
            response = client.post("/session/ingress/enable_caption", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )


# ==================== DISABLE CAPTION TESTS ====================


class TestDisableCaption:
    """Tests for POST /session/ingress/caption/disable endpoint."""

    def test_disable_caption_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_caption_worker: MagicMock,
        sample_session: SessionResponse,
    ):
        """Should successfully disable captions."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session
        mock_task = MagicMock()
        mock_task.id = "test_job_123"
        with patch("app.api.v1.routers.session_ingress_caption.stop_caption_agent") as mock_stop:
            mock_stop.enqueue = AsyncMock(return_value=mock_task)

            payload = {
                "session_id": sample_session.session_id,
            }

            # Act
            response = client.post("/session/ingress/disable_caption", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == sample_session.session_id
        assert data["results"]["status"] == "stopping"
        assert data["results"]["job_id"] == "test_job_123"

    def test_disable_caption_forbidden_wrong_user(
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
        response = client.post("/session/ingress/disable_caption", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["errcode"] == "E_SESSION_FORBIDDEN"


# ==================== GET CAPTION STATUS TESTS ====================


class TestGetCaptionStatus:
    """Tests for POST /session/ingress/caption/status endpoint."""

    def test_get_caption_status_enabled(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return caption status when enabled."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        with patch(
            "app.api.v1.routers.session_ingress_caption.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.hgetall.return_value = {
                b"status": b"running",
                b"started_at": b"2025-12-06T10:00:00Z",
            }
            mock_get_redis.return_value = mock_redis

            response = client.post("/session/ingress/get_caption_status", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == sample_session.session_id
        assert data["results"]["enabled"] is True
        assert data["results"]["status"] == "running"

    def test_get_caption_status_not_enabled(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return not enabled when no agent running."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
        }

        # Act
        with patch(
            "app.api.v1.routers.session_ingress_caption.get_redis_client"
        ) as mock_get_redis:
            mock_redis = AsyncMock()
            mock_redis.hgetall.return_value = {}  # No agent data
            mock_get_redis.return_value = mock_redis

            response = client.post("/session/ingress/get_caption_status", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["enabled"] is False
        assert data["results"]["status"] == "not_running"


# ==================== UPDATE PARTICIPANT LANGUAGE TESTS ====================


class TestUpdateParticipantLanguage:
    """Tests for POST /session/ingress/caption/update-language endpoint."""

    def test_update_language_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully update participant language."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
            "participant_identity": "participant_123",
            "language": "zh",
        }

        # Act
        with patch("app.services.integrations.livekit_service.livekit_service") as mock_livekit:
            mock_livekit.update_participant = AsyncMock()

            response = client.post("/session/ingress/update-language", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == sample_session.session_id
        assert data["results"]["participant_identity"] == "participant_123"
        assert data["results"]["language"] == "zh"
        assert data["results"]["status"] == "updated"

        mock_livekit.update_participant.assert_called_once_with(
            room=sample_session.room_id,
            identity="participant_123",
            attributes={"stt_language": "zh"},
        )

    def test_update_language_with_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should successfully update language using room_id."""
        # Arrange
        mock_session_service.get_active_session_by_room_id.return_value = sample_session

        payload = {
            "room_id": "room_test_123",
            "participant_identity": "participant_456",
            "language": "es",
        }

        # Act
        with patch("app.services.integrations.livekit_service.livekit_service") as mock_livekit:
            mock_livekit.update_participant = AsyncMock()

            response = client.post("/session/ingress/update-language", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["language"] == "es"
        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_test_123"
        )

    def test_update_language_missing_id_fields(
        self,
        client: TestClient,
    ):
        """Should fail when neither session_id nor room_id is provided."""
        # Arrange
        payload = {
            "participant_identity": "participant_123",
            "language": "zh",
        }

        # Act
        response = client.post("/session/ingress/update-language", json=payload)

        # Assert
        assert response.status_code == 400

    def test_update_language_livekit_error(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        sample_session: SessionResponse,
    ):
        """Should return error when LiveKit update fails."""
        # Arrange
        mock_session_service.get_session.return_value = sample_session

        payload = {
            "session_id": sample_session.session_id,
            "participant_identity": "participant_123",
            "language": "zh",
        }

        # Act - The service layer catches exceptions and raises AppError
        with patch(
            "app.services.integrations.livekit_service.livekit_service.update_participant",
            new_callable=AsyncMock,
            side_effect=AppError(
                errcode=AppErrorCode.E_PARTICIPANT_LANGUAGE_UPDATE_FAILED,
                errmesg="Failed to update participant: LiveKit error",
                status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
            ),
        ):
            response = client.post("/session/ingress/update-language", json=payload)

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_PARTICIPANT_LANGUAGE_UPDATE_FAILED"
