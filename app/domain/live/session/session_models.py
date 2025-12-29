"""Session domain models."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas import MuxPlaybackId, SessionState
from app.schemas.session_runtime import SessionRuntime


class SessionResponse(BaseModel):
    """Session response model."""

    session_id: str
    room_id: str
    channel_id: str
    user_id: str

    # Session descriptor fields
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None

    # Session settings
    status: SessionState
    max_participants: int | None = None

    # Scheduling
    schedule_start: datetime | None = None
    schedule_end: datetime | None = None

    # Provider configuration
    runtime: SessionRuntime = Field(default_factory=SessionRuntime)

    # Provider status tracking
    provider_status: dict | None = None

    # Timestamps
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None


class LiveStreamStartResponse(BaseModel):
    """Response model for starting a live stream."""

    egress_id: str
    mux_stream_id: str
    mux_stream_key: str
    mux_rtmp_url: str
    mux_playback_ids: list[MuxPlaybackId]


class SessionListResponse(BaseModel):
    """Session list response with pagination."""

    sessions: list[SessionResponse]
    next_cursor: str | None = None


class SessionCreateParams(BaseModel):
    """Parameters for creating a session."""

    channel_id: str
    user_id: str
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None
    schedule_start: datetime | None = None
    schedule_end: datetime | None = None
    runtime: SessionRuntime | None = None
    end_existing: bool = False


class SessionUpdateParams(BaseModel):
    """Parameters for updating a session."""

    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None

    max_participants: int | None = None
