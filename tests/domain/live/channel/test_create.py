"""Tests for channel creation."""

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams
from app.schemas import Channel
from app.utils.flc_errors import FlcError


@pytest.mark.usefixtures("clear_collections")
class TestCreateChannel:
    """Tests for channel creation."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    async def test_create_channel_success(self, beanie_db, service: ChannelService):
        """Test successful channel creation with all fields."""
        params = ChannelCreateParams(
            user_id="user_123",
            title="Test Channel",
            location="US",
            description="A test channel description",
            cover="https://example.com/cover.jpg",
            lang="en",
            category_ids=["cat1", "cat2"],
        )

        result = await service.create_channel(params)

        assert result.channel_id is not None
        assert result.channel_id.startswith("ch_")
        assert result.user_id == "user_123"
        assert result.title == "Test Channel"
        assert result.location == "US"
        assert result.description == "A test channel description"
        assert result.cover == "https://example.com/cover.jpg"
        assert result.lang == "en"
        assert result.category_ids == ["cat1", "cat2"]
        assert result.created_at is not None
        assert result.updated_at is not None

        # Verify persisted to database
        saved = await Channel.find_one(Channel.channel_id == result.channel_id)
        assert saved is not None

    async def test_create_channel_minimal_fields(self, beanie_db, service: ChannelService):
        """Test channel creation with only required fields."""
        params = ChannelCreateParams(
            user_id="user_456",
            title="Minimal Channel",
            location="GB",
        )

        result = await service.create_channel(params)

        assert result.channel_id is not None
        assert result.user_id == "user_456"
        assert result.title == "Minimal Channel"
        assert result.location == "GB"
        assert result.description is None
        assert result.cover is None
        assert result.lang is None
        assert result.category_ids is None

    async def test_create_channel_missing_title_raises_error(
        self, beanie_db, service: ChannelService
    ):
        """Test that missing title raises FlcError."""
        params = ChannelCreateParams(
            user_id="user_789",
            title=None,
            location="US",
        )

        with pytest.raises(FlcError, match="Title is required"):
            await service.create_channel(params)

    async def test_create_channel_missing_location_raises_error(
        self, beanie_db, service: ChannelService
    ):
        """Test that missing location raises FlcError."""
        params = ChannelCreateParams(
            user_id="user_789",
            title="Test Channel",
            location=None,
        )

        with pytest.raises(FlcError, match="Location is required"):
            await service.create_channel(params)

    async def test_create_multiple_channels_same_user(self, beanie_db, service: ChannelService):
        """Test that a user can create multiple channels."""
        params1 = ChannelCreateParams(
            user_id="user_multi",
            title="Channel 1",
            location="US",
        )
        params2 = ChannelCreateParams(
            user_id="user_multi",
            title="Channel 2",
            location="GB",
        )

        result1 = await service.create_channel(params1)
        result2 = await service.create_channel(params2)

        assert result1.channel_id != result2.channel_id
        assert result1.user_id == result2.user_id == "user_multi"

        # Verify both are persisted
        channels = await Channel.find(Channel.user_id == "user_multi").to_list()
        assert len(channels) == 2
