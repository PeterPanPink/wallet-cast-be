from typing import Annotated

from fastapi import Depends, Request
from loguru import logger
from pydantic import BaseModel
from redis.asyncio import Redis

from app.shared.api.core_api.auth.verify_token import verify_token
from app.shared.api.utils import get_redis_major_client
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

# Redis key for user whitelist set
# Contains user_ids that are allowed access, or "ALL" to allow everyone
USER_WHITELIST_KEY = "wallet-cast-demo:user_whitelist"


class User(BaseModel):
    user_id: str


async def check_user_in_whitelist(redis_client: Redis, user_id: str) -> bool:
    """Check if user_id is in the whitelist or if whitelist contains 'ALL'."""
    # Check if "ALL" is in the whitelist (allows everyone)
    is_all: int = await redis_client.sismember(USER_WHITELIST_KEY, "ALL")  # type: ignore[misc]
    if is_all:
        return True
    # Check if specific user_id is in the whitelist
    is_member: int = await redis_client.sismember(USER_WHITELIST_KEY, user_id)  # type: ignore[misc]
    return bool(is_member)


async def get_current_user(
    request: Request, redis_client: Redis = Depends(get_redis_major_client)
) -> User | None:
    # Do not log request headers here (may include secrets like Authorization).
    user_info = await verify_token(request, redis_client)
    if not user_info:
        raise AppError(
            errcode=AppErrorCode.E_BAD_TOKEN,
            errmesg="Invalid token",
            status_code=HttpStatusCode.UNAUTHORIZED,
        )

    user_id = user_info.get("user_id")
    if not user_id:
        raise AppError(
            errcode=AppErrorCode.E_BAD_TOKEN,
            errmesg="Invalid token",
            status_code=HttpStatusCode.UNAUTHORIZED,
        )

    logger.debug("Authenticated user_id: {}", user_id)

    # Check if user is in whitelist
    if not await check_user_in_whitelist(redis_client, user_id):
        raise AppError(
            errcode=AppErrorCode.E_NOT_WHITELISTED,
            errmesg="User not in whitelist",
            status_code=HttpStatusCode.FORBIDDEN,
        )

    return User(**user_info)


CurrentUser = Annotated[User, Depends(get_current_user)]
