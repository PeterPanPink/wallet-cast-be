"""Unit tests for channel router endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.dependency import User, get_current_user
from app.api.v1.errors import app_error_handler
from app.api.v1.routers.channel import get_channel_service, router
from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelListResponse, ChannelResponse
from app.schemas.user_configs import UserConfigs
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


@pytest.fixture
def mock_user() -> User:
    """Create a mock authenticated user."""
    return User(user_id="test_user_123")


@pytest.fixture
def mock_channel_service() -> AsyncMock:
    """Create a mock ChannelService."""
    return AsyncMock(spec=ChannelService)


@pytest.fixture
def test_app(mock_user: User, mock_channel_service: AsyncMock) -> FastAPI:
    """Create FastAPI test app with dependency overrides."""
    app = FastAPI()

    # Override authentication dependency
    app.dependency_overrides[get_current_user] = lambda: mock_user

    # Override service dependency
    app.dependency_overrides[get_channel_service] = lambda: mock_channel_service

    # Add exception handler for AppError
    app.add_exception_handler(AppError, app_error_handler)  # type: ignore[arg-type]

    app.include_router(router)
    return app


@pytest.fixture
def client(test_app: FastAPI) -> TestClient:
    """Create test client."""
    return TestClient(test_app)


class TestCreateChannel:
    """Tests for POST /channel/create_channel endpoint."""

    def test_create_channel_success(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should successfully create a channel."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        now = datetime.now(timezone.utc)
        mock_channel_service.create_channel.return_value = ChannelResponse(
            channel_id=channel_id,
            user_id="test_user_123",
            title="Test Channel",
            location="US",
            description="Test description",
            cover="https://example.com/cover.jpg",
            lang="en",
            category_ids=["cat1", "cat2"],
            user_configs=UserConfigs(),
            created_at=now,
            updated_at=now,
        )

        payload = {
            "title": "Test Channel",
            "location": "US",
            "description": "Test description",
            "cover": "https://example.com/cover.jpg",
            "lang": "en",
            "category_ids": ["cat1", "cat2"],
        }

        # Act
        response = client.post("/channel/create_channel", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["channel_id"] == channel_id
        mock_channel_service.create_channel.assert_called_once()

    def test_create_channel_minimal_fields(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should create channel with only required fields."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        now = datetime.now(timezone.utc)
        mock_channel_service.create_channel.return_value = ChannelResponse(
            channel_id=channel_id,
            user_id="test_user_123",
            title="Minimal Channel",
            location="CA",
            description=None,
            cover=None,
            lang=None,
            category_ids=None,
            user_configs=UserConfigs(),
            created_at=now,
            updated_at=now,
        )

        payload = {
            "title": "Minimal Channel",
            "location": "CA",
        }

        # Act
        response = client.post("/channel/create_channel", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "channel_id" in data["results"]

    def test_create_channel_invalid_location(self, client: TestClient):
        """Should reject invalid country code."""
        # Arrange
        payload = {
            "title": "Test Channel",
            "location": "INVALID",  # Not a valid ISO 3166-1 alpha-2 code
        }

        # Act
        response = client.post("/channel/create_channel", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_create_channel_too_many_categories(self, client: TestClient):
        """Should reject more than 3 category IDs."""
        # Arrange
        payload = {
            "title": "Test Channel",
            "location": "US",
            "category_ids": ["cat1", "cat2", "cat3", "cat4"],  # Too many
        }

        # Act
        response = client.post("/channel/create_channel", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error

    def test_create_channel_invalid_language(self, client: TestClient):
        """Should reject invalid language code."""
        # Arrange
        payload = {
            "title": "Test Channel",
            "location": "US",
            "lang": "INVALID",  # Not a valid ISO 639-1 code
        }

        # Act
        response = client.post("/channel/create_channel", json=payload)

        # Assert
        assert response.status_code == 400  # Custom validation error


class TestListChannels:
    """Tests for GET /channel/list_channels endpoint."""

    def test_list_channels_success(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should successfully list channels for user."""
        # Arrange
        now = datetime.now(timezone.utc)
        channels = [
            ChannelResponse(
                channel_id=f"ch_{i}",
                user_id="test_user_123",
                title=f"Channel {i}",
                location="US",
                description=f"Description {i}",
                cover=None,
                lang="en",
                category_ids=None,
                user_configs=UserConfigs(),
                created_at=now,
                updated_at=now,
            )
            for i in range(3)
        ]

        mock_channel_service.list_channels_for_user.return_value = ChannelListResponse(
            channels=channels,
            next_cursor="next_page_cursor",
        )

        # Act
        response = client.get("/channel/list_channels")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert len(data["results"]["channels"]) == 3
        assert data["results"]["next_cursor"] == "next_page_cursor"
        mock_channel_service.list_channels_for_user.assert_called_once()

    def test_list_channels_with_pagination(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should support pagination parameters."""
        # Arrange
        mock_channel_service.list_channels_for_user.return_value = ChannelListResponse(
            channels=[],
            next_cursor=None,
        )

        # Act
        response = client.get(
            "/channel/list_channels",
            params={"cursor": "some_cursor", "page_size": 10},
        )

        # Assert
        assert response.status_code == 200
        call_args = mock_channel_service.list_channels_for_user.call_args
        assert call_args.kwargs["cursor"] == "some_cursor"
        assert call_args.kwargs["page_size"] == 10

    def test_list_channels_empty_result(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should handle empty channel list."""
        # Arrange
        mock_channel_service.list_channels_for_user.return_value = ChannelListResponse(
            channels=[],
            next_cursor=None,
        )

        # Act
        response = client.get("/channel/list_channels")

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["channels"] == []
        assert data["results"]["next_cursor"] is None

    def test_list_channels_invalid_page_size(self, client: TestClient):
        """Should reject invalid page_size values."""
        # Act
        response = client.get(
            "/channel/list_channels",
            params={"page_size": 0},  # Too small
        )

        # Assert
        assert response.status_code == 422  # Validation error

    def test_list_channels_page_size_too_large(self, client: TestClient):
        """Should reject page_size above maximum."""
        # Act
        response = client.get(
            "/channel/list_channels",
            params={"page_size": 101},  # Above max of 100
        )

        # Assert
        assert response.status_code == 422  # Validation error


class TestUpdateChannel:
    """Tests for POST /channel/update_channel endpoint."""

    def test_update_channel_success(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should successfully update channel."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        now = datetime.now(timezone.utc)
        mock_channel_service.update_channel.return_value = ChannelResponse(
            channel_id=channel_id,
            user_id="test_user_123",
            title="Updated Title",
            location="US",
            description="Updated description",
            cover="https://example.com/new_cover.jpg",
            lang="en",
            category_ids=["cat1"],
            user_configs=UserConfigs(),
            created_at=now,
            updated_at=now,
        )

        payload = {
            "channel_id": channel_id,
            "title": "Updated Title",
            "description": "Updated description",
            "cover": "https://example.com/new_cover.jpg",
        }

        # Act
        response = client.post("/channel/update_channel", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["channel_id"] == channel_id
        assert data["results"]["title"] == "Updated Title"
        mock_channel_service.update_channel.assert_called_once()

    def test_update_channel_partial_update(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should allow partial updates."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        now = datetime.now(timezone.utc)
        mock_channel_service.update_channel.return_value = ChannelResponse(
            channel_id=channel_id,
            user_id="test_user_123",
            title="Original Title",
            location="US",
            description="Updated description only",
            cover=None,
            lang="en",
            category_ids=None,
            user_configs=UserConfigs(),
            created_at=now,
            updated_at=now,
        )

        payload = {
            "channel_id": channel_id,
            "description": "Updated description only",
        }

        # Act
        response = client.post("/channel/update_channel", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_update_channel_not_found(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should return 404 when channel not found."""
        # Arrange
        mock_channel_service.update_channel.side_effect = AppError(
            errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
            errmesg="Channel not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "channel_id": "nonexistent_channel",
            "title": "New Title",
        }

        # Act
        response = client.post("/channel/update_channel", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_CHANNEL_NOT_FOUND"

    def test_update_channel_unauthorized_user(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should reject update from unauthorized user."""
        # Arrange
        mock_channel_service.update_channel.side_effect = AppError(
            errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
            errmesg="Not authorized",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "channel_id": "ch_someone_else",
            "title": "Hacked Title",
        }

        # Act
        response = client.post("/channel/update_channel", json=payload)

        # Assert
        assert response.status_code == 404

    def test_update_channel_partial_update_only_title(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should only pass provided fields to service (exclude_unset behavior).

        When only title is provided, other fields should NOT be passed as None.
        """
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        now = datetime.now(timezone.utc)
        mock_channel_service.update_channel.return_value = ChannelResponse(
            channel_id=channel_id,
            user_id="test_user_123",
            title="New Title",
            location="US",
            description="Original Description",
            cover="https://example.com/original.jpg",
            lang="en",
            category_ids=["cat1"],
            user_configs=UserConfigs(),
            created_at=now,
            updated_at=now,
        )

        # Only send channel_id and title - no other fields
        payload = {
            "channel_id": channel_id,
            "title": "New Title",
        }

        # Act
        response = client.post("/channel/update_channel", json=payload)

        # Assert
        assert response.status_code == 200
        mock_channel_service.update_channel.assert_called_once()

        # Verify that the params only contain title, not other fields as None
        call_kwargs = mock_channel_service.update_channel.call_args.kwargs
        params = call_kwargs["params"]

        # The params should only have title set, other fields should be unset
        params_dict = params.model_dump(exclude_unset=True)
        assert params_dict == {"title": "New Title"}
        # Verify that description and cover are NOT in the unset dict
        assert "description" not in params_dict
        assert "cover" not in params_dict


class TestGetUserConfigs:
    """Tests for GET /channel/get_user_configs endpoint."""

    def test_get_user_configs_success(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should successfully retrieve user configs."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        mock_channel_service.get_user_configs.return_value = UserConfigs(
            echo_cancellation=True,
            noise_suppression=False,
            auto_gain_control=True,
        )

        # Act
        response = client.get(
            "/channel/get_user_configs",
            params={"channel_id": channel_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["channel_id"] == channel_id
        assert data["results"]["echo_cancellation"] is True
        assert data["results"]["noise_suppression"] is False
        assert data["results"]["auto_gain_control"] is True

    def test_get_user_configs_channel_not_found(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should return 404 when channel not found."""
        # Arrange
        mock_channel_service.get_user_configs.side_effect = AppError(
            errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
            errmesg="Channel not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        # Act
        response = client.get(
            "/channel/get_user_configs",
            params={"channel_id": "nonexistent"},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_CHANNEL_NOT_FOUND"

    def test_get_user_configs_missing_channel_id(self, client: TestClient):
        """Should require channel_id parameter."""
        # Act
        response = client.get("/channel/get_user_configs")

        # Assert
        assert response.status_code == 422  # Validation error


class TestUpdateUserConfigs:
    """Tests for POST /channel/update_user_configs endpoint."""

    def test_update_user_configs_success(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should successfully update user configs."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        mock_channel_service.update_user_configs.return_value = UserConfigs(
            echo_cancellation=False,
            noise_suppression=True,
            auto_gain_control=False,
        )

        payload = {
            "channel_id": channel_id,
            "echo_cancellation": False,
            "noise_suppression": True,
            "auto_gain_control": False,
        }

        # Act
        response = client.post("/channel/update_user_configs", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["echo_cancellation"] is False
        assert data["results"]["noise_suppression"] is True
        assert data["results"]["auto_gain_control"] is False

    def test_update_user_configs_partial(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should allow partial config updates."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        mock_channel_service.update_user_configs.return_value = UserConfigs(
            echo_cancellation=True,
            noise_suppression=False,
            auto_gain_control=True,
        )

        payload = {
            "channel_id": channel_id,
            "echo_cancellation": False,  # Only update this field
        }

        # Act
        response = client.post("/channel/update_user_configs", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_update_user_configs_channel_not_found(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should return 404 when channel not found."""
        # Arrange
        mock_channel_service.update_user_configs.side_effect = AppError(
            errcode=AppErrorCode.E_CHANNEL_NOT_FOUND,
            errmesg="Channel not found",
            status_code=HttpStatusCode.NOT_FOUND,
        )

        payload = {
            "channel_id": "nonexistent",
            "echo_cancellation": True,
        }

        # Act
        response = client.post("/channel/update_user_configs", json=payload)

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_CHANNEL_NOT_FOUND"

    def test_update_user_configs_all_none(
        self,
        client: TestClient,
        mock_channel_service: AsyncMock,
    ):
        """Should handle all config fields being None."""
        # Arrange
        channel_id = f"ch_{uuid4().hex[:24]}"
        mock_channel_service.update_user_configs.return_value = UserConfigs(
            echo_cancellation=True,
            noise_suppression=True,
            auto_gain_control=False,
        )

        payload = {
            "channel_id": channel_id,
            # All audio configs are None/not provided
        }

        # Act
        response = client.post("/channel/update_user_configs", json=payload)

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
