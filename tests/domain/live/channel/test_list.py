"""Tests for list channel operations."""

import asyncio

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams


@pytest.mark.usefixtures("clear_collections")
class TestListChannels:
    """Tests for list channel operations."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    async def _create_channels(
        self, service: ChannelService, user_id: str, count: int
    ) -> list[str]:
        """Helper to create multiple channels for a user."""
        channel_ids = []
        for i in range(count):
            params = ChannelCreateParams(
                user_id=user_id,
                title=f"Channel {i}",
                location="US",
            )
            result = await service.create_channel(params)
            channel_ids.append(result.channel_id)
            # Small delay to ensure different created_at timestamps
            await asyncio.sleep(0.01)
        return channel_ids

    async def test_list_channels_empty(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test listing channels when none exist."""
        result = await service.list_channels()

        assert result.channels == []
        assert result.next_cursor is None

    async def test_list_channels_returns_all(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test listing all channels."""
        await self._create_channels(service, "user_list", 3)

        result = await service.list_channels()

        assert len(result.channels) == 3

    async def test_list_channels_by_user(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test listing channels filtered by user."""
        await self._create_channels(service, "user_a", 2)
        await self._create_channels(service, "user_b", 3)

        result = await service.list_channels(user_id="user_a")

        assert len(result.channels) == 2
        assert all(ch.user_id == "user_a" for ch in result.channels)

    async def test_list_channels_for_user(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test list_channels_for_user method."""
        await self._create_channels(service, "user_for", 2)
        await self._create_channels(service, "user_other", 3)

        result = await service.list_channels_for_user("user_for")

        assert len(result.channels) == 2
        assert all(ch.user_id == "user_for" for ch in result.channels)

    async def test_list_channels_pagination(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test channel pagination."""
        await self._create_channels(service, "user_page", 5)

        # Get first page
        result1 = await service.list_channels(user_id="user_page", page_size=2)

        assert len(result1.channels) == 2
        assert result1.next_cursor is not None

        # Get second page
        result2 = await service.list_channels(
            user_id="user_page",
            page_size=2,
            cursor=result1.next_cursor,
        )

        assert len(result2.channels) == 2
        assert result2.next_cursor is not None

        # Verify no overlap
        page1_ids = {ch.channel_id for ch in result1.channels}
        page2_ids = {ch.channel_id for ch in result2.channels}
        assert page1_ids.isdisjoint(page2_ids)

    async def test_list_channels_last_page(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test pagination returns no cursor on last page."""
        await self._create_channels(service, "user_last", 3)

        result = await service.list_channels(user_id="user_last", page_size=10)

        assert len(result.channels) == 3
        assert result.next_cursor is None

    async def test_list_channels_descending_order(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test channels are returned in descending order by created_at."""
        channel_ids = await self._create_channels(service, "user_order", 3)

        result = await service.list_channels(user_id="user_order")

        # Most recent first
        assert result.channels[0].channel_id == channel_ids[-1]
        assert result.channels[-1].channel_id == channel_ids[0]

    async def test_list_channels_after_delete(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test listing channels after deletion."""
        channel_ids = await self._create_channels(service, "user_active", 3)

        # Delete one channel
        await service.delete_channel(channel_ids[0], "user_active")

        result = await service.list_channels(user_id="user_active")

        assert len(result.channels) == 2

    async def test_list_channels_invalid_page_size(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that invalid page size falls back to default."""
        await self._create_channels(service, "user_invalid", 3)

        # Page size too large should be capped
        result = await service.list_channels(user_id="user_invalid", page_size=5000)

        # Should fall back to 20 (default) but still return all 3
        assert len(result.channels) == 3

    async def test_list_channels_invalid_cursor(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that invalid cursor is ignored gracefully."""
        await self._create_channels(service, "user_cursor", 3)

        # Invalid cursor format should be ignored
        result = await service.list_channels(
            user_id="user_cursor",
            cursor="invalid_cursor_format",
        )

        # Should return all channels as if no cursor was provided
        assert len(result.channels) == 3

    async def test_list_channels_datetime_serialization(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that datetime fields are correctly serialized/deserialized.

        This test ensures the Beanie query pattern correctly handles datetime
        fields without ValidationError from MongoDB's extended JSON format.
        """
        # Create channels with datetime fields
        await self._create_channels(service, "user_datetime", 2)

        # List channels - this should not raise ValidationError
        result = await service.list_channels(user_id="user_datetime")

        # Assert datetime fields are properly parsed
        assert len(result.channels) == 2
        for ch in result.channels:
            from datetime import datetime

            assert isinstance(ch.created_at, datetime)
            assert isinstance(ch.updated_at, datetime)

    async def test_list_channels_pagination_datetime_cursor(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test pagination cursor correctly handles datetime comparison."""
        # Create 5 channels
        channel_ids = await self._create_channels(service, "user_dt_cursor", 5)

        # Get first page
        page1 = await service.list_channels(user_id="user_dt_cursor", page_size=2)

        assert len(page1.channels) == 2
        assert page1.next_cursor is not None
        # Most recent first
        assert page1.channels[0].channel_id == channel_ids[-1]
        assert page1.channels[1].channel_id == channel_ids[-2]

        # Get second page using cursor - this tests datetime comparison
        page2 = await service.list_channels(
            user_id="user_dt_cursor",
            page_size=2,
            cursor=page1.next_cursor,
        )

        assert len(page2.channels) == 2
        assert page2.next_cursor is not None
        assert page2.channels[0].channel_id == channel_ids[-3]
        assert page2.channels[1].channel_id == channel_ids[-4]

        # Get third page
        page3 = await service.list_channels(
            user_id="user_dt_cursor",
            page_size=2,
            cursor=page2.next_cursor,
        )

        assert len(page3.channels) == 1
        assert page3.next_cursor is None
        assert page3.channels[0].channel_id == channel_ids[0]

    async def test_list_channels_full_pagination_sequence(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test complete pagination through all channels using cursors."""
        # Create 7 channels
        await self._create_channels(service, "user_full_page", 7)

        all_channel_ids: set[str] = set()
        cursor = None
        page_count = 0

        # Paginate through all channels
        while True:
            result = await service.list_channels(
                user_id="user_full_page",
                page_size=3,
                cursor=cursor,
            )

            for ch in result.channels:
                all_channel_ids.add(ch.channel_id)

            page_count += 1
            cursor = result.next_cursor

            if cursor is None:
                break

        # Should have 3 pages (3 + 3 + 1)
        assert page_count == 3
        # Should have seen all 7 channels
        assert len(all_channel_ids) == 7

    async def test_list_channels_for_user_auto_creates_channel_when_none_exist(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that list_channels_for_user auto-creates a channel for new users."""
        user_id = "new_user_no_channels"

        # User has no channels yet
        result = await service.list_channels_for_user(user_id)

        # Should auto-create one channel
        assert len(result.channels) == 1
        assert result.next_cursor is None

        # Verify the auto-created channel has expected defaults
        channel = result.channels[0]
        assert channel.user_id == user_id
        assert channel.title == "My Channel"
        assert channel.location == "US"

        # Calling again should return the same channel (not create another)
        result2 = await service.list_channels_for_user(user_id)
        assert len(result2.channels) == 1
        assert result2.channels[0].channel_id == channel.channel_id

    async def test_list_channels_for_user_no_auto_create_with_cursor(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that auto-creation only happens on first page (no cursor)."""
        user_id = "user_with_cursor"

        # Simulate pagination with a cursor (empty result should not trigger auto-create)
        # Use a fake cursor format
        fake_cursor = "1000000000000|507f1f77bcf86cd799439011"
        result = await service.list_channels_for_user(user_id, cursor=fake_cursor)

        # Should return empty, no auto-creation
        assert len(result.channels) == 0
        assert result.next_cursor is None
