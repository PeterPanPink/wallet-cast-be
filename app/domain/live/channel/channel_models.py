"""Channel domain models."""

from datetime import datetime

from pydantic import BaseModel, field_validator

from app.domain.utils.locale_validators import validate_country_code, validate_language_code
from app.schemas.user_configs import UserConfigs
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


class ChannelResponse(BaseModel):
    """Channel response model."""

    channel_id: str
    user_id: str
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None
    user_configs: UserConfigs
    created_at: datetime
    updated_at: datetime


class ChannelListResponse(BaseModel):
    """Channel list response with pagination."""

    channels: list[ChannelResponse]
    next_cursor: str | None = None


class ChannelCreateParams(BaseModel):
    """Parameters for creating a channel."""

    user_id: str
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_country_code(v)

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str | None) -> str | None:
        return validate_language_code(v)

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        v = [item.strip() for item in v if item.strip()]
        if len(v) > 3:
            raise FlcError(
                errcode=FlcErrorCode.E_INVALID_REQUEST,
                errmesg="category_ids cannot have more than 3 elements",
                status_code=FlcStatusCode.BAD_REQUEST,
            )
        return v


class ChannelUpdateParams(BaseModel):
    """Parameters for updating a channel.

    Note: category_ids, lang, location are intentionally excluded from update.
    These fields exist in the database and are set during channel creation,
    but are not editable after creation.
    """

    title: str | None = None
    description: str | None = None
    cover: str | None = None


class UserConfigsUpdateParams(BaseModel):
    """Parameters for updating user-level audio configs."""

    echo_cancellation: bool | None = None
    noise_suppression: bool | None = None
    auto_gain_control: bool | None = None
