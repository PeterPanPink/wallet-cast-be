"""Tests for user whitelist functionality."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.dependency import (
    USER_WHITELIST_KEY,
    User,
    check_user_in_whitelist,
    get_current_user,
)
from app.utils.app_errors import AppError


class TestCheckUserInWhitelist:
    """Tests for check_user_in_whitelist function."""

    @pytest.mark.asyncio
    async def test_all_in_whitelist_allows_any_user(self):
        """When 'ALL' is in whitelist, any user should be allowed."""
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(side_effect=lambda key, val: 1 if val == "ALL" else 0)

        result = await check_user_in_whitelist(redis_client, "any_user_id")

        assert result is True
        redis_client.sismember.assert_called_once_with(USER_WHITELIST_KEY, "ALL")

    @pytest.mark.asyncio
    async def test_specific_user_in_whitelist(self):
        """When specific user_id is in whitelist, they should be allowed."""
        redis_client = AsyncMock()
        # "ALL" not in whitelist, but user123 is
        redis_client.sismember = AsyncMock(
            side_effect=lambda key, val: 1 if val == "user123" else 0
        )

        result = await check_user_in_whitelist(redis_client, "user123")

        assert result is True
        assert redis_client.sismember.call_count == 2

    @pytest.mark.asyncio
    async def test_user_not_in_whitelist(self):
        """When user_id is not in whitelist and 'ALL' is not set, deny access."""
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(return_value=0)

        result = await check_user_in_whitelist(redis_client, "unknown_user")

        assert result is False
        assert redis_client.sismember.call_count == 2

    @pytest.mark.asyncio
    async def test_empty_whitelist(self):
        """Empty whitelist should deny all users."""
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(return_value=0)

        result = await check_user_in_whitelist(redis_client, "any_user")

        assert result is False


class TestGetCurrentUser:
    """Tests for get_current_user dependency."""

    @pytest.mark.asyncio
    async def test_invalid_token_raises_error(self):
        """Invalid token should raise E_BAD_TOKEN error."""
        request = MagicMock()
        redis_client = AsyncMock()

        with pytest.raises(AppError) as exc_info, pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.api.v1.dependency.verify_token",
                AsyncMock(return_value=None),
            )
            await get_current_user(request, redis_client)

        assert exc_info.value.errcode == "E_BAD_TOKEN"
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_missing_user_id_raises_error(self):
        """Token without user_id should raise E_BAD_TOKEN error."""
        request = MagicMock()
        redis_client = AsyncMock()

        with pytest.raises(AppError) as exc_info, pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.api.v1.dependency.verify_token",
                AsyncMock(return_value={"some_field": "value"}),
            )
            await get_current_user(request, redis_client)

        assert exc_info.value.errcode == "E_BAD_TOKEN"
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_user_not_whitelisted_raises_error(self):
        """User not in whitelist should raise E_NOT_WHITELISTED error."""
        request = MagicMock()
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(return_value=0)

        with pytest.raises(AppError) as exc_info, pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.api.v1.dependency.verify_token",
                AsyncMock(return_value={"user_id": "user123"}),
            )
            await get_current_user(request, redis_client)

        assert exc_info.value.errcode == "E_NOT_WHITELISTED"
        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_whitelisted_user_returns_user(self):
        """Whitelisted user should return User object."""
        request = MagicMock()
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(side_effect=lambda key, val: 1 if val == "ALL" else 0)

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.api.v1.dependency.verify_token",
                AsyncMock(return_value={"user_id": "user123"}),
            )
            result = await get_current_user(request, redis_client)

        assert isinstance(result, User)
        assert result.user_id == "user123"

    @pytest.mark.asyncio
    async def test_specific_user_whitelisted_returns_user(self):
        """Specifically whitelisted user should return User object."""
        request = MagicMock()
        redis_client = AsyncMock()
        redis_client.sismember = AsyncMock(
            side_effect=lambda key, val: 1 if val == "user456" else 0
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "app.api.v1.dependency.verify_token",
                AsyncMock(return_value={"user_id": "user456"}),
            )
            result = await get_current_user(request, redis_client)

        assert isinstance(result, User)
        assert result.user_id == "user456"
