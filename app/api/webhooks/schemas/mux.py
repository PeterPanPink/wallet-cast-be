"""Mux webhook event schemas.

Pydantic models for Mux webhook events.

References:
- https://docs.mux.com/guides/video/listen-for-webhooks
- https://docs.mux.com/api-reference/video#tag/webhooks
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class MuxEventType(str, Enum):
    """Mux webhook event types."""

    # Live stream events
    LIVE_STREAM_CREATED = "video.live_stream.created"
    LIVE_STREAM_CONNECTED = "video.live_stream.connected"
    LIVE_STREAM_ACTIVE = "video.live_stream.active"
    LIVE_STREAM_IDLE = "video.live_stream.idle"
    LIVE_STREAM_RECORDING = "video.live_stream.recording"
    LIVE_STREAM_DISCONNECTED = "video.live_stream.disconnected"
    LIVE_STREAM_DELETED = "video.live_stream.deleted"

    # Asset events
    ASSET_CREATED = "video.asset.created"
    ASSET_READY = "video.asset.ready"
    ASSET_ERRORED = "video.asset.errored"
    ASSET_DELETED = "video.asset.deleted"
    ASSET_LIVE_STREAM_COMPLETED = "video.asset.live_stream_completed"
    ASSET_MASTER_READY = "video.asset.master.ready"
    ASSET_STATIC_RENDITIONS_READY = "video.asset.static_renditions.ready"

    # Upload events
    UPLOAD_CREATED = "video.upload.created"
    UPLOAD_ASSET_CREATED = "video.upload.asset_created"
    UPLOAD_CANCELLED = "video.upload.cancelled"
    UPLOAD_ERRORED = "video.upload.errored"


class MuxEnvironment(BaseModel):
    """Mux environment information."""

    name: str = Field(..., description="Environment name")
    id: str = Field(..., description="Environment ID")


class MuxLiveStreamData(BaseModel):
    """Mux live stream data object."""

    id: str = Field(..., description="Live stream ID")
    created_at: str = Field(..., description="Creation timestamp")
    stream_key: str | None = Field(None, description="Stream key")
    status: str | None = Field(None, description="Stream status (idle/active/disabled)")
    playback_ids: list[dict[str, Any]] = Field(default_factory=list, description="Playback IDs")
    reconnect_window: float | None = Field(None, description="Reconnect window in seconds")
    passthrough: str | None = Field(None, description="Custom passthrough data (our room_id)")
    max_continuous_duration: int | None = Field(None, description="Max continuous duration")
    latency_mode: str | None = Field(None, description="Latency mode (low/standard)")
    test: bool | None = Field(None, description="Test mode flag")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class MuxAssetData(BaseModel):
    """Mux asset data object."""

    id: str = Field(..., description="Asset ID")
    created_at: str = Field(..., description="Creation timestamp")
    status: str = Field(..., description="Asset status (preparing/ready/errored)")
    duration: float | None = Field(None, description="Duration in seconds")
    max_stored_resolution: str | None = Field(None, description="Max resolution")
    max_stored_frame_rate: float | None = Field(None, description="Max frame rate")
    aspect_ratio: str | None = Field(None, description="Aspect ratio")
    playback_ids: list[dict[str, Any]] = Field(default_factory=list, description="Playback IDs")
    tracks: list[dict[str, Any]] = Field(default_factory=list, description="Tracks")
    master_access: str | None = Field(None, description="Master access level")
    mp4_support: str | None = Field(None, description="MP4 support level")
    passthrough: str | None = Field(None, description="Custom passthrough data")
    live_stream_id: str | None = Field(
        None, description="Unique identifier for the live stream (when asset is from live stream)"
    )
    is_live: bool | None = Field(
        None, description="Whether the live stream that created this asset is currently active"
    )

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamCreatedEvent(BaseModel):
    """video.live_stream.created event."""

    type: Literal[MuxEventType.LIVE_STREAM_CREATED] = MuxEventType.LIVE_STREAM_CREATED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamActiveEvent(BaseModel):
    """video.live_stream.active event."""

    type: Literal[MuxEventType.LIVE_STREAM_ACTIVE] = MuxEventType.LIVE_STREAM_ACTIVE
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamIdleEvent(BaseModel):
    """video.live_stream.idle event."""

    type: Literal[MuxEventType.LIVE_STREAM_IDLE] = MuxEventType.LIVE_STREAM_IDLE
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamRecordingEvent(BaseModel):
    """video.live_stream.recording event."""

    type: Literal[MuxEventType.LIVE_STREAM_RECORDING] = MuxEventType.LIVE_STREAM_RECORDING
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamDisconnectedEvent(BaseModel):
    """video.live_stream.disconnected event."""

    type: Literal[MuxEventType.LIVE_STREAM_DISCONNECTED] = MuxEventType.LIVE_STREAM_DISCONNECTED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamDeletedEvent(BaseModel):
    """video.live_stream.deleted event."""

    type: Literal[MuxEventType.LIVE_STREAM_DELETED] = MuxEventType.LIVE_STREAM_DELETED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetCreatedEvent(BaseModel):
    """video.asset.created event."""

    type: Literal[MuxEventType.ASSET_CREATED] = MuxEventType.ASSET_CREATED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetReadyEvent(BaseModel):
    """video.asset.ready event."""

    type: Literal[MuxEventType.ASSET_READY] = MuxEventType.ASSET_READY
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetErroredEvent(BaseModel):
    """video.asset.errored event."""

    type: Literal[MuxEventType.ASSET_ERRORED] = MuxEventType.ASSET_ERRORED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetDeletedEvent(BaseModel):
    """video.asset.deleted event."""

    type: Literal[MuxEventType.ASSET_DELETED] = MuxEventType.ASSET_DELETED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class LiveStreamConnectedEvent(BaseModel):
    """video.live_stream.connected event.

    Fired when a live stream successfully connects (before becoming active).
    """

    type: Literal[MuxEventType.LIVE_STREAM_CONNECTED] = MuxEventType.LIVE_STREAM_CONNECTED
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxLiveStreamData = Field(..., description="Live stream data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetLiveStreamCompletedEvent(BaseModel):
    """video.asset.live_stream_completed event.

    Fired when a live stream completes and the asset is finalized.
    """

    type: Literal[MuxEventType.ASSET_LIVE_STREAM_COMPLETED] = (
        MuxEventType.ASSET_LIVE_STREAM_COMPLETED
    )
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetMasterReadyEvent(BaseModel):
    """video.asset.master.ready event.

    Fired when the master (high-quality source) version of an asset is ready.
    """

    type: Literal[MuxEventType.ASSET_MASTER_READY] = MuxEventType.ASSET_MASTER_READY
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v


class AssetStaticRenditionsReadyEvent(BaseModel):
    """video.asset.static_renditions.ready event.

    Fired when static renditions (MP4 files) for an asset are ready for download.
    """

    type: Literal[MuxEventType.ASSET_STATIC_RENDITIONS_READY] = (
        MuxEventType.ASSET_STATIC_RENDITIONS_READY
    )
    id: str = Field(..., description="Event ID")
    created_at: str = Field(..., description="Event creation timestamp")
    environment: MuxEnvironment = Field(..., description="Environment info")
    data: MuxAssetData = Field(..., description="Asset data")
    object: dict[str, Any] = Field(default_factory=dict, description="Event object metadata")
    accessor_source: str | None = Field(None, description="Accessor source")
    accessor: str | None = Field(None, description="Accessor")
    request_id: str | None = Field(None, description="Request ID")

    @field_validator("created_at", mode="before")
    @classmethod
    def convert_timestamp_to_string(cls, v: Any) -> str:
        """Convert Unix timestamp (int) to string if needed."""
        if isinstance(v, int):
            return str(v)
        return v
