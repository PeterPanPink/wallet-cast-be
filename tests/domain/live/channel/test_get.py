"""Tests for get channel operations."""

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams
from app.utils.app_errors import AppError, AppErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestGetChannel:
    """Tests for get channel operations."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    @pytest.fixture
    async def existing_channel(self, beanie_db, service: ChannelService) -> tuple[str, str]:
        """Create an existing channel and return (channel_id, user_id)."""
        params = ChannelCreateParams(
            user_id="user_get_test",
            title="Test Channel",
            location="US",
            description="Test description",
        )
        result = await service.create_channel(params)
        return result.channel_id, result.user_id

    async def test_get_channel_by_id(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test getting channel by ID without user check."""
        channel_id, _ = existing_channel

        result = await service.get_channel(channel_id)

        assert result.channel_id == channel_id
        assert result.title == "Test Channel"
        assert result.location == "US"

    async def test_get_channel_with_user_id(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test getting channel with user ownership check."""
        channel_id, user_id = existing_channel

        result = await service.get_channel(channel_id, user_id=user_id)

        assert result.channel_id == channel_id
        assert result.user_id == user_id

    async def test_get_channel_not_found(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test getting non-existent channel raises AppError."""
        with pytest.raises(AppError) as exc_info:
            await service.get_channel("non_existent_channel_id")
        assert exc_info.value.errcode == AppErrorCode.E_CHANNEL_NOT_FOUND

    async def test_get_channel_wrong_user(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test getting channel with wrong user raises AppError."""
        channel_id, _ = existing_channel

        with pytest.raises(AppError) as exc_info:
            await service.get_channel(channel_id, user_id="wrong_user")
        assert exc_info.value.errcode == AppErrorCode.E_CHANNEL_NOT_FOUND

    async def test_get_channel_returns_all_fields(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that get_channel returns all channel fields."""
        # Create channel with all fields
        params = ChannelCreateParams(
            user_id="user_full_fields",
            title="Full Channel",
            location="GB",
            description="Full description",
            cover="https://example.com/cover.jpg",
            lang="en",
            category_ids=["cat1", "cat2"],
        )
        created = await service.create_channel(params)

        result = await service.get_channel(created.channel_id)

        assert result.channel_id == created.channel_id
        assert result.user_id == "user_full_fields"
        assert result.title == "Full Channel"
        assert result.location == "GB"
        assert result.description == "Full description"
        assert result.cover == "https://example.com/cover.jpg"
        assert result.lang == "en"
        assert result.category_ids == ["cat1", "cat2"]
        assert result.created_at is not None
        assert result.updated_at is not None
