"""Channel configuration schemas for provider-specific settings."""

from datetime import datetime

from pydantic import BaseModel, Field


class MuxPlaybackId(BaseModel):
    """Mux playback ID information."""

    id: str
    policy: str


class HostCleanupRuntime(BaseModel):
    """Runtime data for host cleanup task.

    When the host leaves the room, a delayed cleanup task is scheduled.
    If the host returns before the delay expires, the task is cancelled.
    """

    task_id: str | None = Field(
        default=None,
        description="Streaq task ID for the scheduled cleanup task",
    )
    host_left_at: datetime | None = Field(
        default=None,
        description="Timestamp when the host left the room",
    )


class LiveKitRuntime(BaseModel):
    egress_id: str | None = None


class MuxRuntime(BaseModel):
    mux_stream_id: str | None = None
    mux_stream_key: str | None = None
    mux_rtmp_url: str | None = None
    mux_playback_ids: list[MuxPlaybackId] | None = None
    mux_active_asset_id: str | None = Field(
        default=None,
        description="Active asset ID for DVR playback. The asset's playback_id should be used "
        "for live_playback_url to enable full timeline scrubbing (DVR mode).",
    )


class SessionRuntime(BaseModel):
    """Configuration for LiveKit provider."""

    # Provider-specific runtime data
    livekit: LiveKitRuntime | None = None
    mux: MuxRuntime | None = None

    # Host cleanup task tracking
    host_cleanup: HostCleanupRuntime | None = Field(
        default=None,
        description="Tracks the scheduled cleanup task when host leaves the room",
    )

    # Playback URLs
    live_playback_url: str | None = Field(
        default=None, description="Live stream playback URL (HLS)"
    )
    vod_playback_url: str | None = Field(
        default=None, description="VOD playback URL (after stream ends)"
    )
    animated_url: str | None = Field(default=None, description="Animated GIF preview URL")
    thumbnail_url: str | None = Field(default=None, description="Thumbnail URL")
    storyboard_url: str | None = Field(
        default=None,
        description="Storyboard VTT URL for progress bar preview",
    )

    # CBX Live integration
    post_id: str | None = Field(
        default=None,
        description="Post ID returned from CBX Live admin/live/start API",
    )
