"""Tests for channel delete operations."""

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams
from app.schemas import Channel


@pytest.mark.usefixtures("clear_collections")
class TestDeleteChannel:
    """Tests for channel delete operations."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    @pytest.fixture
    async def existing_channel(self, beanie_db, service: ChannelService) -> tuple[str, str]:
        """Create an existing channel and return (channel_id, user_id)."""
        params = ChannelCreateParams(
            user_id="user_delete_test",
            title="Channel To Delete",
            location="US",
        )
        result = await service.create_channel(params)
        return result.channel_id, result.user_id

    async def test_delete_channel_success(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test successful channel deletion."""
        channel_id, user_id = existing_channel

        result = await service.delete_channel(channel_id, user_id)

        assert result is True

        # Verify channel is deleted
        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is None

    async def test_delete_channel_not_found(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test deleting non-existent channel returns False."""
        result = await service.delete_channel("non_existent_id", "user_123")

        assert result is False

    async def test_delete_channel_wrong_user(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test deleting channel with wrong user returns False."""
        channel_id, _ = existing_channel

        result = await service.delete_channel(channel_id, "wrong_user")

        assert result is False

        # Verify channel still exists
        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is not None

    async def test_delete_channel_idempotent(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test that deleting an already deleted channel returns False."""
        channel_id, user_id = existing_channel

        # First delete
        result1 = await service.delete_channel(channel_id, user_id)
        assert result1 is True

        # Second delete attempt - should return False
        result2 = await service.delete_channel(channel_id, user_id)
        assert result2 is False

        # Verify channel is deleted
        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is None
