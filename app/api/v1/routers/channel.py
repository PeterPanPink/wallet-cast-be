from fastapi import APIRouter, Depends, Query

from app.api.v1.dependency import CurrentUser
from app.api.v1.schemas.base import ApiOut
from app.api.v1.schemas.channel import (
    ChannelOut,
    CreateChannelIn,
    CreateChannelOut,
    ListChannelsOut,
    UpdateChannelIn,
    UpdateUserConfigsIn,
    UserConfigsOut,
)
from app.domain.live.channel.channel_domain import ChannelService
from app.domain.live.channel.channel_models import (
    ChannelCreateParams,
    ChannelUpdateParams,
    UserConfigsUpdateParams,
)

router = APIRouter(prefix="/channel")

# Singleton instance
_channel_service = ChannelService()


def get_channel_service() -> ChannelService:
    """Get the singleton ChannelService instance."""
    return _channel_service


@router.post("/create_channel", tags=["Dev Only"])
async def create_channel(
    channel: CreateChannelIn,
    user: CurrentUser,
    service: ChannelService = Depends(get_channel_service),
) -> ApiOut[CreateChannelOut]:
    """Create a new channel for the authenticated user."""
    params = ChannelCreateParams(
        user_id=user.user_id,
        title=channel.title,
        location=channel.location,
        description=channel.description,
        cover=channel.cover,
        lang=channel.lang,
        category_ids=channel.category_ids,
    )

    result = await service.create_channel(params)

    return ApiOut[CreateChannelOut](results=CreateChannelOut(channel_id=result.channel_id))


@router.get("/list_channels")
async def list_channels(
    user: CurrentUser,
    service: ChannelService = Depends(get_channel_service),
    cursor: str | None = Query(None, description="Pagination cursor"),
    page_size: int = Query(20, ge=1, le=100, description="Number of items per page"),
) -> ApiOut[ListChannelsOut]:
    """List channels for the authenticated user."""
    result = await service.list_channels_for_user(
        user_id=user.user_id,
        cursor=cursor,
        page_size=page_size,
    )

    channels_out = [
        ChannelOut(
            channel_id=ch.channel_id,
            title=ch.title,
            location=ch.location,
            description=ch.description,
            cover=ch.cover,
            lang=ch.lang,
            category_ids=ch.category_ids,
            created_at=ch.created_at,
        )
        for ch in result.channels
    ]

    return ApiOut[ListChannelsOut](
        results=ListChannelsOut(
            channels=channels_out,
            next_cursor=result.next_cursor,
        )
    )


@router.post("/update_channel")
async def update_channel(
    channel: UpdateChannelIn,
    user: CurrentUser,
    service: ChannelService = Depends(get_channel_service),
) -> ApiOut[ChannelOut]:
    """Update a channel owned by the authenticated user.

    Note: category_ids, lang, location are not editable after channel creation.
    These fields exist in the database but are set only during channel creation.
    """
    # Only include fields that were explicitly provided in the request
    update_data = channel.model_dump(
        exclude_unset=True,
        include={"title", "description", "cover"},
    )
    params = ChannelUpdateParams(**update_data)

    result = await service.update_channel(
        channel_id=channel.channel_id,
        user_id=user.user_id,
        params=params,
    )

    return ApiOut[ChannelOut](
        results=ChannelOut(
            channel_id=result.channel_id,
            title=result.title,
            location=result.location,
            description=result.description,
            cover=result.cover,
            lang=result.lang,
            category_ids=result.category_ids,
            created_at=result.created_at,
        )
    )


@router.get("/get_user_configs", tags=["Next Phase"])
async def get_user_configs(
    user: CurrentUser,
    channel_id: str = Query(..., description="Channel identifier"),
    service: ChannelService = Depends(get_channel_service),
) -> ApiOut[UserConfigsOut]:
    """Fetch user-level audio configuration for a channel."""
    configs = await service.get_user_configs(
        channel_id=channel_id,
        user_id=user.user_id,
    )

    return ApiOut[UserConfigsOut](
        results=UserConfigsOut(
            channel_id=channel_id,
            echo_cancellation=configs.echo_cancellation,
            noise_suppression=configs.noise_suppression,
            auto_gain_control=configs.auto_gain_control,
        )
    )


@router.post("/update_user_configs", tags=["Next Phase"])
async def update_user_configs(
    payload: UpdateUserConfigsIn,
    user: CurrentUser,
    service: ChannelService = Depends(get_channel_service),
) -> ApiOut[UserConfigsOut]:
    """Update user-level audio configuration for a channel."""
    params = UserConfigsUpdateParams(
        echo_cancellation=payload.echo_cancellation,
        noise_suppression=payload.noise_suppression,
        auto_gain_control=payload.auto_gain_control,
    )

    configs = await service.update_user_configs(
        channel_id=payload.channel_id,
        user_id=user.user_id,
        params=params,
    )

    return ApiOut[UserConfigsOut](
        results=UserConfigsOut(
            channel_id=payload.channel_id,
            echo_cancellation=configs.echo_cancellation,
            noise_suppression=configs.noise_suppression,
            auto_gain_control=configs.auto_gain_control,
        )
    )
