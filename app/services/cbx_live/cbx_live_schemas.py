from __future__ import annotations

from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, RootModel


class ChannelConfig(BaseModel):
    """Channel configuration for Admin Start Live.

    Mirrors the fields shown in the Admin Start Live documentation.
    """

    channel_id: str | None = Field(
        default=None,
        alias="channelId",
        validation_alias=AliasChoices("channelId", "channel_id"),
        description="Channel ID",
    )
    ttl: str = Field(..., description="Live stream title")
    img: str = Field(..., description="Cover image URL")
    lang: str = Field(..., description="Language code")
    category_ids: list[str] = Field(
        ...,
        alias="categoryIds",
        validation_alias=AliasChoices("categoryIds", "category_ids"),
        description="Array of category IDs",
    )
    location: str = Field(..., description="Location string")
    dsc: str | None = Field(
        default=None,
        description="Description of the channel",
    )
    auto_start: bool = Field(
        default=False,
        alias="autoStart",
        validation_alias=AliasChoices("autoStart", "auto_start"),
        description="Auto start flag",
    )

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class ThumbnailInfo(BaseModel):
    """Thumbnail information."""

    url: str = Field(..., description="Thumbnail URL")
    width: int = Field(..., description="Thumbnail width")
    height: int = Field(..., description="Thumbnail height")


class SessionConfig(BaseModel):
    """Session configuration for Admin Start Live.

    Mirrors the SessionConfig object in the documentation.
    """

    session_id: str = Field(
        ...,
        alias="sid",
        validation_alias=AliasChoices("sid", "session_id"),
        description="Session ID",
    )
    mux_stream_id: str = Field(..., description="Mux stream ID")
    mux_rtmp_ingest_url: str = Field(..., description="Mux RTMP ingest URL")
    url: str = Field(..., description="HLS stream URL (m3u8)")
    animated_url: str = Field(
        ...,
        alias="animatedUrl",
        validation_alias=AliasChoices("animatedUrl", "animated_url"),
        description="Animated GIF preview URL",
    )
    thumbnail_url: str = Field(
        ...,
        alias="thumbnailUrl",
        validation_alias=AliasChoices("thumbnailUrl", "thumbnail_url"),
        description="Static thumbnail URL",
    )
    thumbnails: str = Field(..., description="Thumbnail VTT URL")

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)


class AdminStartLiveBody(BaseModel):
    """Request body for Admin Start Live."""

    user_id: str = Field(..., description="User ID to start live for")
    channel: ChannelConfig = Field(..., description="Channel configuration")
    session: SessionConfig = Field(..., description="Session configuration")


class AdminStopLiveBody(BaseModel):
    """Request body for Admin Stop Live.

    At least one of user_id or post_id must be provided.
    """

    user_id: str | None = Field(None, description="User ID to stop live for")
    post_id: str | None = Field(None, description="Post ID of the live to stop")


class AdminUpdateLiveBody(BaseModel):
    """Request body for Admin Update Live.

    Updates the title, description, and/or cover of an existing live stream.
    """

    post_id: str = Field(..., description="Post ID of the live to update")
    title: str | None = Field(
        None,
        description="New title for the live stream",
    )
    description: str | None = Field(
        None,
        description="New description for the live stream",
    )
    cover: str | None = Field(
        None,
        description="New cover URL or path",
    )


class LivePostData(BaseModel):
    """Live post data returned by API."""

    post_id: str = Field(..., description="Post ID")
    user_id: str | None = Field(None, description="User ID")
    channel_id: str | None = Field(None, description="Channel ID")
    session_id: str | None = Field(None, description="Session ID")
    title: str | None = Field(None, description="Live stream title")
    cover: str | None = Field(None, description="Cover image URL")
    is_live: bool | None = Field(None, description="Whether the stream is live")
    viewers: int | None = Field(None, description="Number of viewers")
    started_at: int | None = Field(None, description="Start timestamp (milliseconds)")
    updated_at: int | None = Field(None, description="Update timestamp (milliseconds)")
    version: int | None = Field(None, description="Version number")
    url: str | None = Field(None, description="HLS stream URL (m3u8)")
    animated_url: str | None = Field(None, description="Animated GIF preview URL")
    thumbnail_url: str | None = Field(None, description="Static thumbnail URL")
    thumbnails: str | None = Field(None, description="Thumbnail VTT URL")
    mux_stream_id: str | None = Field(None, description="Mux stream ID")
    user_muted: bool | None = Field(None, description="User muted status")
    channel_muted: bool | None = Field(None, description="Channel muted status")
    stopped_at: int | None = Field(None, description="Stop timestamp (milliseconds)")

    model_config = ConfigDict(extra="ignore")


class CbxLiveApiSuccess(BaseModel):
    """CBX Live API success response."""

    version: str = Field(..., description="API version")
    success: Literal[True] = Field(..., description="Success status")
    results: LivePostData = Field(..., description="Response data")

    model_config = ConfigDict(extra="ignore")


class CbxLiveApiFailure(BaseModel):
    """CBX Live API failure response."""

    version: str = Field(..., description="API version")
    success: Literal[False] = Field(..., description="Success status")
    errcode: str = Field(..., description="Error code")
    erresid: str = Field(..., description="Error session ID")
    errmesg: str = Field(..., description="Error message")

    model_config = ConfigDict(extra="ignore")


class CbxLiveApiResponse(RootModel[CbxLiveApiSuccess | CbxLiveApiFailure]):
    """Standard CBX Live API response wrapper.

    Discriminated union that handles both success and failure responses.
    Access the actual response via `.root` attribute.
    """
