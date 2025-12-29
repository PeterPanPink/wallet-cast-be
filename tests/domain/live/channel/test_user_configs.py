"""Tests for user configs operations."""

import pytest

from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import ChannelCreateParams, UserConfigsUpdateParams
from app.schemas import Channel
from app.utils.flc_errors import FlcError, FlcErrorCode


@pytest.mark.usefixtures("clear_collections")
class TestUserConfigs:
    """Tests for user configs operations."""

    @pytest.fixture
    def service(self) -> ChannelService:
        """Create channel service instance."""
        return ChannelService()

    @pytest.fixture
    async def existing_channel(self, beanie_db, service: ChannelService) -> tuple[str, str]:
        """Create an existing channel and return (channel_id, user_id)."""
        params = ChannelCreateParams(
            user_id="user_configs_test",
            title="Config Test Channel",
            location="US",
        )
        result = await service.create_channel(params)
        return result.channel_id, result.user_id

    async def test_get_user_configs_default(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test getting default user configs."""
        channel_id, user_id = existing_channel

        result = await service.get_user_configs(channel_id, user_id)

        # Default values
        assert result.echo_cancellation is True
        assert result.noise_suppression is True
        assert result.auto_gain_control is False

    async def test_get_user_configs_not_found(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test getting user configs for non-existent channel."""
        with pytest.raises(FlcError) as exc_info:
            await service.get_user_configs("non_existent_id", "user_123")
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_get_user_configs_wrong_user(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test getting user configs with wrong user."""
        channel_id, _ = existing_channel

        with pytest.raises(FlcError) as exc_info:
            await service.get_user_configs(channel_id, "wrong_user")
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_update_user_configs_echo_cancellation(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating echo cancellation."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams(echo_cancellation=False)
        result = await service.update_user_configs(channel_id, user_id, params)

        assert result.echo_cancellation is False
        assert result.noise_suppression is True  # Unchanged
        assert result.auto_gain_control is False  # Unchanged

    async def test_update_user_configs_noise_suppression(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating noise suppression."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams(noise_suppression=False)
        result = await service.update_user_configs(channel_id, user_id, params)

        assert result.noise_suppression is False

    async def test_update_user_configs_auto_gain_control(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating auto gain control."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams(auto_gain_control=True)
        result = await service.update_user_configs(channel_id, user_id, params)

        assert result.auto_gain_control is True

    async def test_update_user_configs_multiple_fields(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating multiple configs at once."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams(
            echo_cancellation=False,
            noise_suppression=False,
            auto_gain_control=True,
        )
        result = await service.update_user_configs(channel_id, user_id, params)

        assert result.echo_cancellation is False
        assert result.noise_suppression is False
        assert result.auto_gain_control is True

    async def test_update_user_configs_not_found(
        self,
        beanie_db,
        service: ChannelService,
    ):
        """Test updating user configs for non-existent channel."""
        params = UserConfigsUpdateParams(echo_cancellation=False)

        with pytest.raises(FlcError) as exc_info:
            await service.update_user_configs("non_existent_id", "user_123", params)
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_update_user_configs_wrong_user(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating user configs with wrong user."""
        channel_id, _ = existing_channel
        params = UserConfigsUpdateParams(echo_cancellation=False)

        with pytest.raises(FlcError) as exc_info:
            await service.update_user_configs(channel_id, "wrong_user", params)
        assert exc_info.value.errcode == FlcErrorCode.E_CHANNEL_NOT_FOUND

    async def test_update_user_configs_empty_params(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test updating user configs with empty params."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams()
        result = await service.update_user_configs(channel_id, user_id, params)

        # Should return unchanged defaults
        assert result.echo_cancellation is True
        assert result.noise_suppression is True
        assert result.auto_gain_control is False

    async def test_update_user_configs_persists_to_db(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test that user config updates are persisted to database."""
        channel_id, user_id = existing_channel

        params = UserConfigsUpdateParams(echo_cancellation=False)
        await service.update_user_configs(channel_id, user_id, params)

        # Re-fetch from database
        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is not None
        assert saved.user_configs.echo_cancellation is False

    async def test_update_user_configs_updates_timestamp(
        self,
        beanie_db,
        service: ChannelService,
        existing_channel: tuple[str, str],
    ):
        """Test that updating user configs updates the channel updated_at."""
        channel_id, user_id = existing_channel

        original = await Channel.find_one(Channel.channel_id == channel_id)
        assert original is not None
        original_updated_at = original.updated_at

        params = UserConfigsUpdateParams(echo_cancellation=False)
        await service.update_user_configs(channel_id, user_id, params)

        saved = await Channel.find_one(Channel.channel_id == channel_id)
        assert saved is not None
        assert saved.updated_at >= original_updated_at
