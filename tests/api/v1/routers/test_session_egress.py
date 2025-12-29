"""Unit tests for session_egress router endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.dependency import User, get_current_user
from app.api.v1.errors import app_error_handler
from app.api.v1.routers.session_egress import get_session_service, router
from app.domain.live.session.session_domain import SessionService
from app.domain.live.session.session_models import LiveStreamStartResponse, SessionResponse
from app.schemas import MuxPlaybackId, SessionState
from app.schemas.session_runtime import LiveKitRuntime, MuxRuntime, SessionRuntime
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
def test_app(mock_user: User, mock_session_service: AsyncMock) -> FastAPI:
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
def mock_session_response(mock_user: User) -> SessionResponse:
    """Create a mock session response."""
    now = datetime.now(timezone.utc)
    return SessionResponse(
        session_id="sess_123",
        room_id="room_123",
        channel_id="ch_123",
        user_id=mock_user.user_id,
        title="Test Session",
        status=SessionState.READY,
        runtime=SessionRuntime(),
        created_at=now,
        updated_at=now,
    )


@pytest.fixture
def mock_live_stream_response() -> LiveStreamStartResponse:
    """Create a mock live stream start response."""
    return LiveStreamStartResponse(
        egress_id="egress_123",
        mux_stream_id="mux_stream_123",
        mux_stream_key="mux_key_123",
        mux_rtmp_url="rtmps://global-live.mux.com:443/app",
        mux_playback_ids=[
            MuxPlaybackId(id="playback_123", policy="public"),
        ],
    )


class TestStartLiveStream:
    """Tests for POST /session/egress/start_live_stream endpoint."""

    def test_start_live_stream_with_session_id_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
        mock_live_stream_response: LiveStreamStartResponse,
    ):
        """Should successfully start live stream using session_id."""
        # Arrange
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.start_live.return_value = mock_live_stream_response

        payload = {
            "session_id": "sess_123",
            "layout": "speaker",
            "base_path": "/demo",
        }

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["egress_id"] == "egress_123"
        assert data["results"]["mux_stream_id"] == "mux_stream_123"
        assert data["results"]["mux_stream_key"] == "mux_key_123"
        assert data["results"]["mux_rtmp_url"] == "rtmps://global-live.mux.com:443/app"
        assert len(data["results"]["mux_playback_ids"]) == 1
        assert data["results"]["mux_playback_ids"][0]["id"] == "playback_123"

        mock_session_service.get_session.assert_called_once_with(session_id="sess_123")
        mock_session_service.start_live.assert_called_once_with(
            room_name="room_123",
            layout="speaker",
            referer=None,
            base_path="/demo",
            width=1920,
            height=1080,
            is_mobile=False,
        )

    def test_start_live_stream_with_room_id_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
        mock_live_stream_response: LiveStreamStartResponse,
    ):
        """Should successfully start live stream using room_id."""
        # Arrange
        mock_session_service.get_active_session_by_room_id.return_value = mock_session_response
        mock_session_service.start_live.return_value = mock_live_stream_response

        payload = {
            "room_id": "room_123",
            "layout": "grid",
        }

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["egress_id"] == "egress_123"

        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_123"
        )
        mock_session_service.start_live.assert_called_once_with(
            room_name="room_123",
            layout="grid",
            referer=None,
            base_path=None,
            width=1920,
            height=1080,
            is_mobile=False,
        )

    def test_start_live_stream_with_referer_header(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
        mock_live_stream_response: LiveStreamStartResponse,
    ):
        """Should pass referer header to service."""
        # Arrange
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.start_live.return_value = mock_live_stream_response

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post(
            "/session/egress/start_live_stream",
            json=payload,
            headers={"referer": "https://example.com/page"},
        )

        # Assert
        assert response.status_code == 200
        mock_session_service.start_live.assert_called_once_with(
            room_name="room_123",
            layout="speaker",
            referer="https://example.com/page",
            base_path=None,
            width=1920,
            height=1080,
            is_mobile=False,
        )

    def test_start_live_stream_missing_both_ids(self, client: TestClient):
        """Should reject request when both session_id and room_id are missing."""
        # Arrange
        payload = {"layout": "speaker"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_start_live_stream_both_ids_provided(self, client: TestClient):
        """Should reject request when both session_id and room_id are provided."""
        # Arrange
        payload = {
            "session_id": "sess_123",
            "room_id": "room_123",
            "layout": "speaker",
        }

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_start_live_stream_session_not_found(
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

        payload = {"session_id": "nonexistent_sess"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"
        # Error message comes from the service layer, not modified by router
        assert "Session not found" in data["errmesg"]

    def test_start_live_stream_unauthorized_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 403 when user doesn't own the session."""
        # Arrange
        mock_session_response.user_id = "different_user"
        mock_session_service.get_session.return_value = mock_session_response

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_start_live_stream_already_exists_idempotent(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return existing stream data when already in progress (idempotent)."""
        # Arrange
        mock_session_service.get_session.return_value = mock_session_response

        # Mock service.start_live to return existing egress data (idempotent)
        mock_session_service.start_live.return_value = LiveStreamStartResponse(
            egress_id="existing_egress_123",
            mux_stream_id="existing_mux_123",
            mux_stream_key="existing_key_123",
            mux_rtmp_url="rtmps://global-live.mux.com:443/app",
            mux_playback_ids=[MuxPlaybackId(id="existing_playback_123", policy="public")],
        )

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["egress_id"] == "existing_egress_123"
        assert data["results"]["mux_stream_id"] == "existing_mux_123"

    def test_start_live_stream_already_exists_no_data(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 409 when stream exists but no egress data available."""
        # Arrange
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.start_live.side_effect = AppError(
            errcode=AppErrorCode.E_LIVE_STREAM_IN_PROGRESS,
            errmesg="Stream already in progress",
            status_code=HttpStatusCode.CONFLICT,
        )

        # Session has incomplete egress info
        session_incomplete = mock_session_response.model_copy()
        session_incomplete.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123")
        )  # Incomplete - no mux data
        mock_session_service.get_session.side_effect = [
            mock_session_response,
            session_incomplete,
        ]

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_LIVE_STREAM_IN_PROGRESS"

    def test_start_live_stream_invalid_config_type(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should handle session with invalid config type gracefully."""
        # Arrange
        mock_session_response.runtime = SessionRuntime()  # Empty config
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.start_live.side_effect = AppError(
            errcode=AppErrorCode.E_LIVE_STREAM_IN_PROGRESS,
            errmesg="Stream already in progress",
            status_code=HttpStatusCode.CONFLICT,
        )

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert - Should return 409 since no valid egress data
        assert response.status_code == 409

    def test_start_live_stream_flc_error(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should propagate AppError from service layer."""
        # Arrange
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.start_live.side_effect = AppError(
            errcode=AppErrorCode.E_LIVE_STREAM_START_FAILED,
            errmesg="Failed to start stream",
            status_code=HttpStatusCode.INTERNAL_SERVER_ERROR,
        )

        payload = {"session_id": "sess_123"}

        # Act
        response = client.post("/session/egress/start_live_stream", json=payload)

        # Assert
        assert response.status_code == 500
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_LIVE_STREAM_START_FAILED"


class TestEndLiveStream:
    """Tests for POST /session/egress/end_live_stream endpoint."""

    def test_end_live_stream_with_session_id_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should successfully end live stream using session_id."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=MuxRuntime(mux_stream_id="mux_stream_123"),
        )
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.end_live.return_value = None

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["message"] == "Live stream ended successfully"
        assert data["results"]["session_id"] == "sess_123"

        mock_session_service.get_session.assert_called_once_with(session_id="sess_123")
        mock_session_service.end_live.assert_called_once_with(
            room_name="room_123",
            egress_id="egress_123",
            mux_stream_id="mux_stream_123",
        )

    def test_end_live_stream_with_room_id_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should successfully end live stream using room_id."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=MuxRuntime(mux_stream_id="mux_stream_123"),
        )
        mock_session_service.get_active_session_by_room_id.return_value = mock_session_response
        mock_session_service.end_live.return_value = None

        payload = {
            "room_id": "room_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        mock_session_service.get_active_session_by_room_id.assert_called_once_with(
            room_id="room_123"
        )

    def test_end_live_stream_missing_both_ids(self, client: TestClient):
        """Should reject request when both session_id and room_id are missing."""
        # Arrange
        payload = {
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_end_live_stream_both_ids_provided(self, client: TestClient):
        """Should reject request when both session_id and room_id are provided."""
        # Arrange
        payload = {
            "session_id": "sess_123",
            "room_id": "room_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_end_live_stream_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 200 when session not found (stream already ended)."""
        # Arrange
        mock_session_service.get_session.side_effect = AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "session_id": "nonexistent_sess",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert - session not found means stream already ended, return success
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["message"] == "Live stream already ended"

    def test_end_live_stream_unauthorized_user(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 403 when user doesn't own the session."""
        # Arrange
        mock_session_response.user_id = "different_user"
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=MuxRuntime(mux_stream_id="mux_stream_123"),
        )
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_end_live_stream_invalid_config_type(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 200 when session has empty config (no egress info) - idempotent."""
        # Arrange
        mock_session_response.runtime = SessionRuntime()  # Empty config
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert - no egress info means stream already ended, return success (idempotent)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["message"] == "Live stream already ended"

    def test_end_live_stream_missing_egress_info(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 200 when session has no active egress info - idempotent."""
        # Arrange
        mock_session_response.runtime = SessionRuntime()  # No egress data
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert - no egress info means stream already ended, return success (idempotent)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["message"] == "Live stream already ended"

    def test_end_live_stream_egress_id_mismatch(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 400 when provided egress_id doesn't match session."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="different_egress"),
            mux=MuxRuntime(mux_stream_id="mux_stream_123"),
        )
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "wrong_egress",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"
        assert "egress_id does not match" in data["errmesg"]

    def test_end_live_stream_mux_stream_id_mismatch(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 400 when provided mux_stream_id doesn't match session."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=MuxRuntime(mux_stream_id="different_mux_stream"),
        )
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "wrong_mux_stream",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"
        assert "mux_stream_id does not match" in data["errmesg"]

    def test_end_live_stream_value_error(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should propagate AppError from service layer."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=MuxRuntime(mux_stream_id="mux_stream_123"),
        )
        mock_session_service.get_session.return_value = mock_session_response
        mock_session_service.end_live.side_effect = AppError(
            errcode=AppErrorCode.E_INVALID_REQUEST,
            errmesg="Invalid state",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"
        assert "Invalid state" in data["errmesg"]

    def test_end_live_stream_partial_egress_info(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_session_response: SessionResponse,
    ):
        """Should return 200 when session has only egress_id but no mux_stream_id - idempotent."""
        # Arrange
        mock_session_response.runtime = SessionRuntime(
            livekit=LiveKitRuntime(egress_id="egress_123"),
            mux=None,  # Missing mux data
        )
        mock_session_service.get_session.return_value = mock_session_response

        payload = {
            "session_id": "sess_123",
            "egress_id": "egress_123",
            "mux_stream_id": "mux_stream_123",
        }

        # Act
        response = client.post("/session/egress/end_live_stream", json=payload)

        # Assert - incomplete egress info means stream already ended, return success (idempotent)
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["message"] == "Live stream already ended"
