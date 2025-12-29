from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.schemas import MuxPlaybackId
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode


class ClientPlatform(str, Enum):
    """Platform from which the request originates."""

    WEB = "web"
    MOBILE = "mobile"


class StartLiveStreamIn(BaseModel):
    """Request to start a live stream for a session."""

    session_id: str | None = Field(
        default=None, description="Session ID to start live streaming for"
    )
    room_id: str | None = Field(default=None, description="Room ID to start live streaming for")
    layout: str = Field(
        default="speaker",
        description="Layout for the composite stream (e.g., 'speaker', 'grid')",
    )
    platform: ClientPlatform = Field(
        default=ClientPlatform.WEB,
        description="Platform from which the request originates (web or mobile)",
    )
    base_path: str | None = Field(
        default=None,
        description="Frontend base path for recording URL (e.g., '/demo')",
    )
    width: int = Field(
        default=1920,
        description="Video width in pixels (default: 1920)",
        ge=320,
        le=3840,
    )
    height: int = Field(
        default=1080,
        description="Video height in pixels (default: 1080)",
        ge=180,
        le=2160,
    )

    @model_validator(mode="after")
    def validate_id_fields(self):
        if not self.session_id and not self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Either session_id or room_id must be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        if self.session_id and self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Only one of session_id or room_id can be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        return self


class StartLiveStreamOut(BaseModel):
    """Response after starting a live stream."""

    egress_id: str = Field(description="LiveKit egress ID")
    mux_stream_id: str = Field(description="Mux stream ID")
    mux_stream_key: str = Field(description="Mux stream key")
    mux_rtmp_url: str = Field(description="Mux RTMP URL")
    mux_playback_ids: list[MuxPlaybackId] = Field(
        description="Mux playback IDs for viewing the stream"
    )


class EndLiveStreamIn(BaseModel):
    """Request to end a live stream for a session."""

    session_id: str | None = Field(default=None, description="Session ID to end streaming for")
    room_id: str | None = Field(default=None, description="Room ID to end streaming for")
    egress_id: str = Field(description="LiveKit egress ID to stop")
    mux_stream_id: str = Field(description="Mux stream ID to complete")

    @model_validator(mode="after")
    def validate_id_fields(self):
        if not self.session_id and not self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Either session_id or room_id must be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        if self.session_id and self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Only one of session_id or room_id can be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        return self


class EndLiveStreamOut(BaseModel):
    """Response after ending a live stream."""

    message: str = Field(description="Success message")
    session_id: str = Field(description="Session ID that was stopped")


class UpdateRoomMetadataIn(BaseModel):
    """Request to update room metadata for a session."""

    session_id: str | None = Field(default=None, description="Session ID to update metadata for")
    room_id: str | None = Field(default=None, description="Room ID to update metadata for")
    metadata: str = Field(
        description="JSON string containing room metadata (max 64 KiB)",
        max_length=65536,
    )

    @model_validator(mode="after")
    def validate_id_fields(self):
        if not self.session_id and not self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Either session_id or room_id must be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        if self.session_id and self.room_id:
            raise AppError(
                errcode=AppErrorCode.E_INVALID_REQUEST,
                errmesg="Only one of session_id or room_id can be provided",
                status_code=HttpStatusCode.BAD_REQUEST,
            )
        return self


class UpdateRoomMetadataOut(BaseModel):
    """Response after updating room metadata."""

    room: str = Field(description="Room name")
    sid: str = Field(description="Room SID")
    metadata: str = Field(description="Updated metadata JSON string")


class TranscriptItem(BaseModel):
    """Individual transcript item."""

    text: str = Field(description="Transcript text")
    language: str | None = Field(default=None, description="Original language code")
    confidence: float | None = Field(default=None, description="Transcription confidence")
    start_time: float = Field(description="Start time in seconds")
    end_time: float = Field(description="End time in seconds")
    duration: float = Field(description="Duration in seconds")
    speaker_id: str | None = Field(default=None, description="Speaker identifier")
    participant_identity: str | None = Field(default=None, description="Participant identity")
    translations: dict[str, str] | None = Field(
        default=None, description="Translations by language code"
    )
    created_at: str = Field(description="Creation timestamp")


class GetTranscriptsOut(BaseModel):
    """Response with list of transcripts."""

    session_id: str = Field(description="Session ID")
    transcripts: list[TranscriptItem] = Field(description="List of transcript items")
    total_count: int = Field(description="Total number of transcripts")
    language_filter: str | None = Field(default=None, description="Applied language filter")
