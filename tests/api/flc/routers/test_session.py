"""Unit tests for session router endpoints.

Tests for FastAPI session endpoints that handle session lifecycle operations:
- Creating sessions
- Listing sessions with pagination and filters
- Getting sessions by ID or room_id
- Updating session metadata
- Ending sessions
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.flc.dependency import User, get_current_user
from app.api.flc.errors import app_error_handler
from app.api.flc.routers.session import get_session_service, router
from app.domain.live.session.session_domain import SessionService
from app.domain.live.session.session_models import SessionListResponse, SessionResponse
from app.schemas import SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


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

    # Add exception handler for FlcError
    app.add_exception_handler(FlcError, app_error_handler)  # type: ignore[arg-type]

    app.include_router(router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(test_app)


def create_mock_session_response(
    session_id: str | None = None,
    channel_id: str = "ch_test123",
    user_id: str = "test_user_123",
    status: SessionState = SessionState.IDLE,
    **kwargs,
) -> SessionResponse:
    """Helper to create mock session responses."""
    session_id = session_id or f"sess_{uuid4().hex[:24]}"
    now = datetime.now(timezone.utc)

    return SessionResponse(
        session_id=session_id,
        room_id=session_id,  # room_id equals session_id
        channel_id=channel_id,
        user_id=user_id,
        title=kwargs.get("title", "Test Session"),
        location=kwargs.get("location", "US"),
        description=kwargs.get("description"),
        cover=kwargs.get("cover"),
        lang=kwargs.get("lang", "en"),
        category_ids=kwargs.get("category_ids"),
        status=status,
        max_participants=kwargs.get("max_participants", 100),
        schedule_start=kwargs.get("schedule_start"),
        schedule_end=kwargs.get("schedule_end"),
        runtime=kwargs.get("runtime", SessionRuntime()),
        provider_status=kwargs.get("provider_status"),
        created_at=kwargs.get("created_at", now),
        updated_at=kwargs.get("updated_at", now),
        started_at=kwargs.get("started_at"),
        stopped_at=kwargs.get("stopped_at"),
    )


class TestCreateSession:
    """Tests for POST /flc/session/create_session endpoint."""

    def test_create_session_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should successfully create a session."""
        # Arrange
        session_id = f"sess_{uuid4().hex[:24]}"
        mock_session_service.create_session.return_value = create_mock_session_response(
            session_id=session_id,
            channel_id="ch_test123",
        )

        payload = {
            "channel_id": "ch_test123",
            "title": "My Live Stream",
            "location": "US",
            "description": "Test description",
            "cover": "https://example.com/cover.jpg",
            "lang": "en",
            "category_ids": ["cat1", "cat2"],
        }

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == session_id
        assert data["results"]["room_id"] == session_id
        mock_session_service.create_session.assert_called_once()

    def test_create_session_minimal_fields(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should create session with only required channel_id."""
        # Arrange
        session_id = f"sess_{uuid4().hex[:24]}"
        mock_session_service.create_session.return_value = create_mock_session_response(
            session_id=session_id,
            title=None,
            location=None,
            description=None,
        )

        payload = {"channel_id": "ch_test123"}

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "session_id" in data["results"]

    def test_create_session_with_end_existing(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should create session with end_existing flag."""
        # Arrange
        session_id = f"sess_{uuid4().hex[:24]}"
        mock_session_service.create_session.return_value = create_mock_session_response(
            session_id=session_id,
        )

        payload = {
            "channel_id": "ch_test123",
            "title": "New Session",
            "end_existing": True,
        }

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        mock_session_service.create_session.assert_called_once()

    def test_create_session_channel_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when channel doesn't exist."""
        # Arrange
        mock_session_service.create_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_CHANNEL_NOT_FOUND,
            errmesg="Channel not found",
            status_code=FlcStatusCode.NOT_FOUND,
        )

        payload = {"channel_id": "nonexistent_channel"}

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_CHANNEL_NOT_FOUND"
        assert "Channel not found" in data["errmesg"]

    def test_create_session_already_exists(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 409 when active session already exists."""
        # Arrange
        mock_session_service.create_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_EXISTS,
            errmesg="An active session already exists for this channel",
            status_code=FlcStatusCode.CONFLICT,
        )

        payload = {"channel_id": "ch_test123"}

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 409
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_EXISTS"
        assert "already exists" in data["errmesg"]

    def test_create_session_invalid_location(
        self,
        client: TestClient,
    ):
        """Should reject invalid country code."""
        # Arrange
        payload = {
            "channel_id": "ch_test123",
            "location": "INVALID",
        }

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_create_session_invalid_lang(
        self,
        client: TestClient,
    ):
        """Should reject invalid language code."""
        # Arrange
        payload = {
            "channel_id": "ch_test123",
            "lang": "invalid_lang",
        }

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_create_session_too_many_categories(
        self,
        client: TestClient,
    ):
        """Should reject more than 3 category_ids."""
        # Arrange
        payload = {
            "channel_id": "ch_test123",
            "category_ids": ["cat1", "cat2", "cat3", "cat4"],
        }

        # Act
        response = client.post("/flc/session/create_session", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error


class TestListSessions:
    """Tests for GET /flc/session/list_sessions endpoint."""

    def test_list_sessions_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should successfully list sessions."""
        # Arrange
        sessions = [
            create_mock_session_response(
                session_id="sess1",
                status=SessionState.LIVE,
            ),
            create_mock_session_response(
                session_id="sess2",
                status=SessionState.STOPPED,
            ),
        ]
        mock_session_service.list_sessions.return_value = SessionListResponse(
            sessions=sessions,
            next_cursor="cursor_123",
        )

        # Act
        response = client.get("/flc/session/list_sessions")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]["sessions"]) == 2
        assert data["results"]["next_cursor"] == "cursor_123"
        assert data["results"]["sessions"][0]["session_id"] == "sess1"

    def test_list_sessions_with_pagination(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should list sessions with pagination parameters."""
        # Arrange
        mock_session_service.list_sessions.return_value = SessionListResponse(
            sessions=[],
            next_cursor=None,
        )

        # Act
        response = client.get(
            "/flc/session/list_sessions",
            params={"cursor": "cursor_abc", "page_size": 10},
        )

        # Assert
        assert response.status_code == 200
        call_args = mock_session_service.list_sessions.call_args[1]
        assert call_args["cursor"] == "cursor_abc"
        assert call_args["page_size"] == 10

    def test_list_sessions_with_channel_filter(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should filter sessions by channel_id."""
        # Arrange
        mock_session_service.list_sessions.return_value = SessionListResponse(
            sessions=[],
            next_cursor=None,
        )

        # Act
        response = client.get(
            "/flc/session/list_sessions",
            params={"channel_id": "ch_test123"},
        )

        # Assert
        assert response.status_code == 200
        call_args = mock_session_service.list_sessions.call_args[1]
        assert call_args["channel_id"] == "ch_test123"

    def test_list_sessions_with_status_filter(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should filter sessions by status."""
        # Arrange
        mock_session_service.list_sessions.return_value = SessionListResponse(
            sessions=[],
            next_cursor=None,
        )

        # Act
        response = client.get(
            "/flc/session/list_sessions",
            params={"status": ["live", "ready"]},
        )

        # Assert
        assert response.status_code == 200
        call_args = mock_session_service.list_sessions.call_args[1]
        assert call_args["status"] == [SessionState.LIVE, SessionState.READY]

    def test_list_sessions_empty_result(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return empty list when no sessions exist."""
        # Arrange
        mock_session_service.list_sessions.return_value = SessionListResponse(
            sessions=[],
            next_cursor=None,
        )

        # Act
        response = client.get("/flc/session/list_sessions")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["sessions"] == []
        assert data["results"]["next_cursor"] is None

    def test_list_sessions_invalid_page_size(
        self,
        client: TestClient,
    ):
        """Should reject page_size outside valid range."""
        # Act
        response = client.get(
            "/flc/session/list_sessions",
            params={"page_size": 200},  # Max is 100
        )

        # Assert
        assert response.status_code == 422  # Validation error


class TestGetSession:
    """Tests for GET /flc/session/get_session endpoint."""

    def test_get_session_by_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should get session by session_id."""
        # Arrange
        session_id = "sess_test123"
        mock_session_service.get_session.return_value = create_mock_session_response(
            session_id=session_id,
        )

        # Act
        response = client.get(
            "/flc/session/get_session",
            params={"session_id": session_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == session_id
        mock_session_service.get_session.assert_called_once_with(session_id=session_id)

    def test_get_session_by_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should get active session by room_id."""
        # Arrange
        room_id = "room_test123"
        mock_session_service.get_active_session_by_room_id.return_value = (
            create_mock_session_response(
                session_id=room_id,
                status=SessionState.LIVE,
            )
        )

        # Act
        response = client.get(
            "/flc/session/get_session",
            params={"room_id": room_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room_id"] == room_id
        mock_session_service.get_active_session_by_room_id.assert_called_once_with(room_id=room_id)

    def test_get_session_no_params(
        self,
        client: TestClient,
    ):
        """Should return 400 when neither session_id nor room_id provided."""
        # Act
        response = client.get("/flc/session/get_session")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"

    def test_get_session_both_params(
        self,
        client: TestClient,
    ):
        """Should return 400 when both session_id and room_id provided."""
        # Act
        response = client.get(
            "/flc/session/get_session",
            params={"session_id": "sess1", "room_id": "room1"},
        )

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"

    def test_get_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=FlcStatusCode.NOT_FOUND,
        )

        # Act
        response = client.get(
            "/flc/session/get_session",
            params={"session_id": "nonexistent"},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"


class TestGetActiveSession:
    """Tests for GET /flc/session/get_active_session endpoint."""

    def test_get_active_session_success(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should get active session for channel."""
        # Arrange
        channel_id = "ch_test123"
        mock_session_service.get_active_session_by_channel.return_value = (
            create_mock_session_response(
                channel_id=channel_id,
                user_id=mock_user.user_id,
                status=SessionState.LIVE,
            )
        )

        # Act
        response = client.get(
            "/flc/session/get_active_session",
            params={"channel_id": channel_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["channel_id"] == channel_id
        assert data["results"]["status"] == "live"

    def test_get_active_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when no active session exists."""
        # Arrange
        mock_session_service.get_active_session_by_channel.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
            errmesg="No active session",
            status_code=FlcStatusCode.NOT_FOUND,
        )

        # Act
        response = client.get(
            "/flc/session/get_active_session",
            params={"channel_id": "ch_test123"},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"

    def test_get_active_session_forbidden(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should return 403 when user doesn't own the session."""
        # Arrange
        mock_session_service.get_active_session_by_channel.return_value = (
            create_mock_session_response(
                user_id="different_user",  # Different from mock_user
            )
        )

        # Act
        response = client.get(
            "/flc/session/get_active_session",
            params={"channel_id": "ch_test123"},
        )

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_get_active_session_missing_channel_id(
        self,
        client: TestClient,
    ):
        """Should return 422 when channel_id is missing."""
        # Act
        response = client.get("/flc/session/get_active_session")

        # Assert
        assert response.status_code == 422  # Validation error


class TestUpdateSession:
    """Tests for POST /flc/session/update_session endpoint."""

    def test_update_session_by_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should update session by session_id."""
        # Arrange
        session_id = "sess_test123"
        existing = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
        )
        updated = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            title="Updated Title",
        )
        mock_session_service.get_session.return_value = existing
        mock_session_service.update_session.return_value = updated

        payload = {
            "session_id": session_id,
            "title": "Updated Title",
        }

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["title"] == "Updated Title"
        mock_session_service.get_session.assert_called_once_with(session_id=session_id)
        mock_session_service.update_session.assert_called_once()

    def test_update_session_by_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should update session by room_id."""
        # Arrange
        room_id = "room_test123"
        existing = create_mock_session_response(
            session_id=room_id,
            user_id=mock_user.user_id,
        )
        updated = create_mock_session_response(
            session_id=room_id,
            user_id=mock_user.user_id,
            description="Updated description",
        )
        mock_session_service.get_active_session_by_room_id.return_value = existing
        mock_session_service.update_session.return_value = updated

        payload = {
            "room_id": room_id,
            "description": "Updated description",
        }

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["description"] == "Updated description"

    def test_update_session_all_fields(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should update all allowed fields."""
        # Arrange
        session_id = "sess_test123"
        existing = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
        )
        updated = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            title="New Title",
            location="CA",
            description="New description",
            cover="https://example.com/new.jpg",
            lang="fr",
            category_ids=["cat3"],
        )
        mock_session_service.get_session.return_value = existing
        mock_session_service.update_session.return_value = updated

        payload = {
            "session_id": session_id,
            "title": "New Title",
            "location": "CA",
            "description": "New description",
            "cover": "https://example.com/new.jpg",
            "lang": "fr",
            "category_ids": ["cat3"],
        }

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["title"] == "New Title"
        assert data["results"]["location"] == "CA"

    def test_update_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=FlcStatusCode.NOT_FOUND,
        )

        payload = {"session_id": "nonexistent"}

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"

    def test_update_session_forbidden(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 403 when user doesn't own the session."""
        # Arrange
        mock_session_service.get_session.return_value = create_mock_session_response(
            user_id="different_user",
        )

        payload = {"session_id": "sess_test123", "title": "New Title"}

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_update_session_no_id_provided(
        self,
        client: TestClient,
    ):
        """Should return 400 when neither session_id nor room_id provided."""
        # Arrange
        payload = {"title": "New Title"}

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_update_session_both_ids_provided(
        self,
        client: TestClient,
    ):
        """Should return 400 when both session_id and room_id provided."""
        # Arrange
        payload = {
            "session_id": "sess1",
            "room_id": "room1",
            "title": "New Title",
        }

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_update_session_partial_update_only_title(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should only pass provided fields to service (exclude_unset behavior).

        When only title is provided, other fields should NOT be passed as None.
        """
        # Arrange
        session_id = "sess_partial"
        existing = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            title="Original Title",
            description="Original Description",
            location="US",
            lang="en",
            category_ids=["cat1", "cat2"],
        )
        updated = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            title="New Title",
            description="Original Description",
            location="US",
            lang="en",
            category_ids=["cat1", "cat2"],
        )
        mock_session_service.get_session.return_value = existing
        mock_session_service.update_session.return_value = updated

        # Only send session_id and title - no other fields
        payload = {
            "session_id": session_id,
            "title": "New Title",
        }

        # Act
        response = client.post("/flc/session/update_session", json=payload)

        # Assert
        assert response.status_code == 200
        mock_session_service.update_session.assert_called_once()

        # Verify that the params only contain title, not other fields as None
        call_kwargs = mock_session_service.update_session.call_args.kwargs
        params = call_kwargs["params"]

        # The params should only have title set, other fields should be unset (None by default)
        params_dict = params.model_dump(exclude_unset=True)
        assert params_dict == {"title": "New Title"}
        # Verify that description, location, etc. are NOT in the unset dict
        assert "description" not in params_dict
        assert "location" not in params_dict
        assert "lang" not in params_dict
        assert "category_ids" not in params_dict


class TestEndSession:
    """Tests for POST /flc/session/end_session endpoint."""

    def test_end_session_by_session_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should end session by session_id."""
        # Arrange
        session_id = "sess_test123"
        existing = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            status=SessionState.LIVE,
        )
        ended = create_mock_session_response(
            session_id=session_id,
            user_id=mock_user.user_id,
            status=SessionState.STOPPED,
        )
        mock_session_service.get_session.return_value = existing
        mock_session_service.end_session.return_value = ended

        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"session_id": session_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["session_id"] == session_id
        assert data["results"]["status"] == "stopped"
        mock_session_service.end_session.assert_called_once_with(session_id=session_id)

    def test_end_session_by_room_id(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should end session by room_id."""
        # Arrange
        room_id = "room_test123"
        existing = create_mock_session_response(
            session_id=room_id,
            user_id=mock_user.user_id,
            status=SessionState.LIVE,
        )
        ended = create_mock_session_response(
            session_id=room_id,
            user_id=mock_user.user_id,
            status=SessionState.STOPPED,
        )
        mock_session_service.get_active_session_by_room_id.return_value = existing
        mock_session_service.end_session.return_value = ended

        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"room_id": room_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["room_id"] == room_id

    def test_end_session_no_params(
        self,
        client: TestClient,
    ):
        """Should return 400 when neither session_id nor room_id provided."""
        # Act
        response = client.post("/flc/session/end_session")

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"

    def test_end_session_both_params(
        self,
        client: TestClient,
    ):
        """Should return 400 when both session_id and room_id provided."""
        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"session_id": "sess1", "room_id": "room1"},
        )

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_INVALID_REQUEST"

    def test_end_session_not_found(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 404 when session not found."""
        # Arrange
        mock_session_service.get_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
            errmesg="Session not found",
            status_code=FlcStatusCode.NOT_FOUND,
        )

        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"session_id": "nonexistent"},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"

    def test_end_session_forbidden(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
    ):
        """Should return 403 when user doesn't own the session."""
        # Arrange
        mock_session_service.get_session.return_value = create_mock_session_response(
            user_id="different_user",
        )

        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"session_id": "sess_test123"},
        )

        # Assert
        assert response.status_code == 403
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_FORBIDDEN"

    def test_end_session_invalid_state(
        self,
        client: TestClient,
        mock_session_service: AsyncMock,
        mock_user: User,
    ):
        """Should return 400 when session in invalid state for ending."""
        # Arrange
        existing = create_mock_session_response(
            user_id=mock_user.user_id,
            status=SessionState.STOPPED,
        )
        mock_session_service.get_session.return_value = existing
        mock_session_service.end_session.side_effect = FlcError(
            errcode=FlcErrorCode.E_SESSION_END_FAILED,
            errmesg="Session already stopped",
            status_code=FlcStatusCode.BAD_REQUEST,
        )

        # Act
        response = client.post(
            "/flc/session/end_session",
            params={"session_id": "sess_test123"},
        )

        # Assert
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_END_FAILED"
