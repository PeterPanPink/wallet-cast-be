from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from .serializers import serialize_utc_datetime
from .validators import validate_country_code, validate_language_code


class CreateChannelIn(BaseModel):
    title: str = Field(description="Title of the channel")
    location: str = Field(description="ISO 3166-1 alpha-2 country code")
    description: str | None = Field(default=None, description="Description of the channel")
    cover: str | None = Field(default=None, description="URL of the cover image")
    lang: str | None = Field(default=None, description="ISO 639-1 language code")
    category_ids: list[str] | None = Field(
        default=None, description="List of category IDs, max 3 elements"
    )

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str) -> str:
        return validate_country_code(v)

    @field_validator("category_ids")
    @classmethod
    def validate_category_ids(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v

        v = [item.strip() for item in v if item.strip()]
        if len(v) > 3:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="category_ids cannot have more than 3 elements",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        return v

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str | None) -> str | None:
        return validate_language_code(v)


class CreateChannelOut(BaseModel):
    channel_id: str = Field(description="Unique identifier for the created channel")


class UpdateChannelIn(BaseModel):
    channel_id: str = Field(description="Unique identifier for the channel to update")
    title: str | None = Field(default=None, description="Title of the channel")
    description: str | None = Field(default=None, description="Description of the channel")
    cover: str | None = Field(default=None, description="URL of the cover image")


class ChannelOut(BaseModel):
    channel_id: str
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None
    created_at: datetime

    @field_serializer("created_at")
    @classmethod
    def serialize_datetime(cls, v: datetime) -> str:
        return serialize_utc_datetime(v)


class ListChannelsOut(BaseModel):
    channels: list[ChannelOut]
    next_cursor: str | None = None


class UpdateUserConfigsIn(BaseModel):
    channel_id: str = Field(description="Channel identifier")
    echo_cancellation: bool | None = Field(
        default=None, description="Enable or disable echo cancellation"
    )
    noise_suppression: bool | None = Field(
        default=None, description="Enable or disable noise suppression"
    )
    auto_gain_control: bool | None = Field(
        default=None, description="Enable or disable automatic gain control"
    )


class UserConfigsOut(BaseModel):
    channel_id: str
    echo_cancellation: bool
    noise_suppression: bool
    auto_gain_control: bool
