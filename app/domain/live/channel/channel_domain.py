"""Channel domain service - Batch operations with MongoDB/Beanie."""

from loguru import logger
from redis.exceptions import RedisError

from app.app_config import get_app_environ_config
from app.cw.config import custom_config
from app.cw.lock import LockManager
from app.cw.storage.redis import get_redis_client
from app.schemas.user_configs import UserConfigs

from ._channels import ChannelOperations
from .channel_models import (
    ChannelCreateParams,
    ChannelListResponse,
    ChannelResponse,
    ChannelUpdateParams,
    UserConfigsUpdateParams,
)


class ChannelService:
    """Batch-oriented channel service."""

    def __init__(self):
        self._channels = ChannelOperations()

    # ==================== CHANNELS ====================

    async def create_channel(
        self,
        params: ChannelCreateParams,
    ) -> ChannelResponse:
        """Create a channel for the requesting user."""
        return await self._channels.create_channel(
            params=params,
        )

    async def update_channel(
        self,
        channel_id: str,
        user_id: str,
        params: ChannelUpdateParams,
    ) -> ChannelResponse:
        """Update channel metadata for the given user.

        Raises FlcError if channel not found/unauthorized.
        """
        return await self._channels.update_channel(
            channel_id=channel_id,
            user_id=user_id,
            params=params,
        )

    async def get_channel(
        self,
        channel_id: str,
        user_id: str | None = None,
    ) -> ChannelResponse:
        """Get a single channel by ID with optional user ownership check.

        Raises FlcError if channel not found.
        """
        return await self._channels.get_channel(
            channel_id=channel_id,
            user_id=user_id,
        )

    async def list_channels(
        self,
        cursor: str | None = None,
        page_size: int = 20,
        user_id: str | None = None,
    ) -> ChannelListResponse:
        """Return paginated channels with optional filters."""
        return await self._channels.list_channels(
            cursor=cursor,
            page_size=page_size,
            user_id=user_id,
        )

    async def list_channels_for_user(
        self,
        user_id: str,
        cursor: str | None = None,
        page_size: int = 20,
    ) -> ChannelListResponse:
        """Return paginated channels owned by the given user.

        If the user has no channels, automatically creates a default channel.
        Uses a distributed lock to ensure only one channel is created even
        under concurrent requests.
        """
        result = await self._channels.list_channels(
            cursor=cursor,
            page_size=page_size,
            user_id=user_id,
        )

        # Auto-create a default channel if user has none (only on first page)
        if not result.channels and cursor is None:
            result = await self._create_default_channel_atomic(user_id)

        return result

    async def _create_default_channel_atomic(self, user_id: str) -> ChannelListResponse:
        """Create a default channel atomically using a distributed lock.

        This ensures only one channel is created even if multiple concurrent
        requests arrive for the same user.

        Falls back to non-locked creation if Redis is unavailable (graceful degradation).
        """
        lock = None
        acquired = False

        try:
            redis_major_label = custom_config.get_redis_major_label()
            redis_client = get_redis_client(redis_major_label)
            lock = LockManager(redis_client, lock_prefix="channel_create", default_ttl=30)

            acquired = await lock.acquire(
                user_id,
                blocking=True,
                blocking_timeout=10,
            )
        except (RedisError, ConnectionError, OSError) as e:
            # Redis unavailable - fallback to non-locked creation
            logger.warning(
                f"Redis unavailable for channel lock, falling back to unlocked creation: {e}"
            )
            return await self._create_default_channel_unlocked(user_id)

        try:
            if acquired:
                # Double-check: re-query to see if channel was created by another request
                existing = await self._channels.list_channels(
                    cursor=None,
                    page_size=1,
                    user_id=user_id,
                )
                if existing.channels:
                    return existing

                # Still no channels - create the default one
                default_params = ChannelCreateParams(
                    user_id=user_id,
                    title="My Channel",
                    location="US",
                    category_ids=["other"],
                    lang="en",
                    cover=get_app_environ_config().DEFAULT_CHANNEL_COVER,
                )
                new_channel = await self._channels.create_channel(params=default_params)
                return ChannelListResponse(channels=[new_channel], next_cursor=None)
            else:
                # Lock not acquired within timeout - try fetching again
                # (another request likely created the channel)
                return await self._channels.list_channels(
                    cursor=None,
                    page_size=20,
                    user_id=user_id,
                )
        finally:
            if acquired and lock:
                try:
                    await lock.release()
                except (RedisError, ConnectionError, OSError) as e:
                    logger.warning(f"Failed to release channel lock: {e}")

    async def _create_default_channel_unlocked(self, user_id: str) -> ChannelListResponse:
        """Create a default channel without distributed lock (fallback when Redis unavailable).

        Note: This may result in duplicate channels in rare race conditions,
        but ensures service availability when Redis is down.
        """
        # Re-check if channel exists
        existing = await self._channels.list_channels(
            cursor=None,
            page_size=1,
            user_id=user_id,
        )
        if existing.channels:
            return existing

        # Create default channel
        default_params = ChannelCreateParams(
            user_id=user_id,
            title="My Channel",
            location="US",
            category_ids=["other"],
            lang="en",
            cover=get_app_environ_config().DEFAULT_CHANNEL_COVER,
        )
        new_channel = await self._channels.create_channel(params=default_params)
        return ChannelListResponse(channels=[new_channel], next_cursor=None)

    async def delete_channel(
        self,
        channel_id: str,
        user_id: str,
    ) -> bool:
        """Delete a channel."""
        return await self._channels.delete_channel(
            channel_id=channel_id,
            user_id=user_id,
        )

    async def get_user_configs(
        self,
        channel_id: str,
        user_id: str,
    ) -> UserConfigs:
        """Get user-level audio configs for a channel."""
        return await self._channels.get_user_configs(
            channel_id=channel_id,
            user_id=user_id,
        )

    async def update_user_configs(
        self,
        channel_id: str,
        user_id: str,
        params: UserConfigsUpdateParams,
    ) -> UserConfigs:
        """Update user-level audio configs for a channel."""
        return await self._channels.update_user_configs(
            channel_id=channel_id,
            user_id=user_id,
            params=params,
        )
