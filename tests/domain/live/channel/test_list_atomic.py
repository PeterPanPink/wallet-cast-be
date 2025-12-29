"""Tests for atomic channel creation in list_channels_for_user."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams


def create_mutex_lock_mock():
    """Create a mock LockManager that simulates real mutex behavior."""
    lock_held = asyncio.Lock()
    acquired_by: dict[str, bool] = {}

    class MockLockManager:
        def __init__(self, *args, **kwargs):
            self._lock_id = id(self)

        async def acquire(self, *key_parts, **kwargs):
            # Try to acquire the asyncio lock (simulates Redis lock)
            try:
                await asyncio.wait_for(lock_held.acquire(), timeout=0.1)
                acquired_by[self._lock_id] = True
                return True
            except TimeoutError:
                acquired_by[self._lock_id] = False
                return False

        async def release(self):
            if acquired_by.get(self._lock_id):
                lock_held.release()
                acquired_by[self._lock_id] = False
            return True

    return MockLockManager


@pytest.mark.usefixtures("clear_collections")
class TestAtomicChannelCreation:
    """Tests for atomic channel creation behavior."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    async def test_concurrent_requests_with_mutex_create_only_one_channel(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that concurrent calls with mutex behavior only create one channel."""
        user_id = "user_concurrent"

        # Use a mock that simulates real mutex behavior
        mock_lock_class = create_mutex_lock_mock()

        with (
            patch(
                "app.domain.live.channel.channel_domain.get_redis_client",
                return_value=MagicMock(),
            ),
            patch(
                "app.domain.live.channel.channel_domain.LockManager",
                mock_lock_class,
            ),
        ):
            # Fire 5 concurrent requests
            tasks = [service.list_channels_for_user(user_id) for _ in range(5)]
            results = await asyncio.gather(*tasks)

        # All results should return exactly 1 channel
        for result in results:
            assert len(result.channels) == 1

        # Verify only one channel was created in the database
        all_channels = await service.list_channels(user_id=user_id)
        assert len(all_channels.channels) == 1
        assert all_channels.channels[0].user_id == user_id
        assert all_channels.channels[0].title == "My Channel"

    async def test_double_check_prevents_duplicate_after_lock_acquired(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that double-check after lock prevents duplicate creation."""
        user_id = "user_double_check"

        # Pre-create a channel
        params = ChannelCreateParams(
            user_id=user_id,
            title="Existing Channel",
            location="US",
        )
        await service.create_channel(params)

        # Mock lock to always succeed
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock(return_value=True)

        with patch(
            "app.domain.live.channel.channel_domain.LockManager",
            return_value=mock_lock,
        ):
            result = await service.list_channels_for_user(user_id)

        # Should return the existing channel, not create a new one
        assert len(result.channels) == 1
        assert result.channels[0].title == "Existing Channel"

        # Verify no new channel was created
        all_channels = await service.list_channels(user_id=user_id)
        assert len(all_channels.channels) == 1

    async def test_lock_timeout_returns_existing_channel(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that lock timeout fallback returns existing channel."""
        user_id = "user_lock_timeout"

        # Pre-create a channel
        params = ChannelCreateParams(
            user_id=user_id,
            title="Pre-existing Channel",
            location="CA",
        )
        await service.create_channel(params)

        # Mock lock to fail (simulate timeout)
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=False)
        mock_lock.release = AsyncMock(return_value=True)

        with patch(
            "app.domain.live.channel.channel_domain.LockManager",
            return_value=mock_lock,
        ):
            # Simulate the condition where result is empty initially
            # This triggers the atomic creation path
            result = await service._create_default_channel_atomic(user_id)

        # Should return the existing channel via fallback query
        assert len(result.channels) == 1
        assert result.channels[0].title == "Pre-existing Channel"

    async def test_lock_acquired_creates_channel(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that lock acquisition leads to channel creation."""
        user_id = "user_lock_acquired"

        # Mock lock to succeed
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock(return_value=True)

        with patch(
            "app.domain.live.channel.channel_domain.LockManager",
            return_value=mock_lock,
        ):
            result = await service.list_channels_for_user(user_id)

        # Should create the default channel
        assert len(result.channels) == 1
        assert result.channels[0].user_id == user_id
        assert result.channels[0].title == "My Channel"

        # Verify lock was properly released
        mock_lock.release.assert_called_once()

    async def test_lock_released_on_exception(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that lock is released even if channel creation fails."""
        user_id = "user_lock_exception"

        # Mock lock to succeed
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock(return_value=True)

        with (
            patch(
                "app.domain.live.channel.channel_domain.LockManager",
                return_value=mock_lock,
            ),
            patch.object(
                service._channels,
                "create_channel",
                side_effect=Exception("DB error"),
            ),
            pytest.raises(Exception, match="DB error"),
        ):
            await service._create_default_channel_atomic(user_id)

        # Lock should still be released
        mock_lock.release.assert_called_once()

    async def test_sequential_calls_reuse_existing_channel(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test that sequential calls return the same channel."""
        user_id = "user_sequential"

        # Mock lock to succeed for all calls
        mock_lock = MagicMock()
        mock_lock.acquire = AsyncMock(return_value=True)
        mock_lock.release = AsyncMock(return_value=True)

        with patch(
            "app.domain.live.channel.channel_domain.LockManager",
            return_value=mock_lock,
        ):
            # First call creates the channel
            result1 = await service.list_channels_for_user(user_id)
            assert len(result1.channels) == 1
            channel_id = result1.channels[0].channel_id

            # Subsequent calls return the same channel
            for _ in range(3):
                result = await service.list_channels_for_user(user_id)
                assert len(result.channels) == 1
                assert result.channels[0].channel_id == channel_id

        # Verify only one channel exists
        all_channels = await service.list_channels(user_id=user_id)
        assert len(all_channels.channels) == 1

    async def test_atomic_creation_uses_correct_lock_key(
        self,
        beanie_db,
    ):
        """Test that the lock key is based on user_id."""
        user_id = "user_lock_key"
        service = ChannelService()

        mock_lock_instance = MagicMock()
        mock_lock_instance.acquire = AsyncMock(return_value=True)
        mock_lock_instance.release = AsyncMock(return_value=True)

        with patch(
            "app.domain.live.channel.channel_domain.LockManager",
            return_value=mock_lock_instance,
        ) as mock_lock_class:
            await service._create_default_channel_atomic(user_id)

        # Verify LockManager was initialized with correct prefix
        mock_lock_class.assert_called_once()
        call_kwargs = mock_lock_class.call_args[1]
        assert call_kwargs["lock_prefix"] == "channel_create"

        # Verify acquire was called with user_id
        mock_lock_instance.acquire.assert_called_once_with(
            user_id,
            blocking=True,
            blocking_timeout=10,
        )
