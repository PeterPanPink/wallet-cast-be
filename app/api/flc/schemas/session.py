from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, field_validator, model_validator

from app.schemas.session_runtime import SessionRuntime
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

from .serializers import serialize_optional_utc_datetime
from .validators import validate_country_code, validate_language_code


class CreateSessionIn(BaseModel):
    channel_id: str = Field(description="Channel ID for the session")
    title: str | None = Field(default=None, description="Title of the session")
    location: str | None = Field(default=None, description="ISO 3166-1 alpha-2 country code")
    description: str | None = Field(default=None, description="Description of the session")
    cover: str | None = Field(default=None, description="URL of the cover image")
    lang: str | None = Field(default=None, description="ISO 639-1 language code")
    category_ids: list[str] | None = Field(
        default=None, description="List of category IDs, max 3 elements"
    )
    end_existing: bool = Field(
        default=False,
        description="End existing active session before creating a new one",
    )

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_country_code(v)

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

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_language_code(v)


class CreateSessionOut(BaseModel):
    session_id: str = Field(description="Unique identifier for the created session")
    room_id: str = Field(description="LiveKit room ID (equals session_id)")


class UpdateSessionIn(BaseModel):
    session_id: str | None = Field(
        default=None, description="Unique identifier for the session to update"
    )
    room_id: str | None = Field(default=None, description="Room ID for the session to update")
    title: str | None = Field(default=None, description="Title of the session")
    location: str | None = Field(default=None, description="ISO 3166-1 alpha-2 country code")
    description: str | None = Field(default=None, description="Description of the session")
    cover: str | None = Field(default=None, description="URL of the cover image")
    lang: str | None = Field(default=None, description="ISO 639-1 language code")
    category_ids: list[str] | None = Field(
        default=None, description="List of category IDs, max 3 elements"
    )

    # status CANNOT be updated via this schema
    # status: str

    @model_validator(mode="after")
    def validate_id_fields(self):
        if not self.session_id and not self.room_id:
            raise FlcError(
                errcode=FlcErrorCode.E_INVALID_REQUEST,
                errmesg="Either session_id or room_id must be provided",
                status_code=FlcStatusCode.BAD_REQUEST,
            )
        if self.session_id and self.room_id:
            raise FlcError(
                errcode=FlcErrorCode.E_INVALID_REQUEST,
                errmesg="Only one of session_id or room_id can be provided",
                status_code=FlcStatusCode.BAD_REQUEST,
            )
        return self

    @field_validator("location")
    @classmethod
    def validate_location(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_country_code(v)

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

    @field_validator("lang")
    @classmethod
    def validate_lang(cls, v: str | None) -> str | None:
        if v is None:
            return v
        return validate_language_code(v)


class SessionOut(BaseModel):
    session_id: str
    room_id: str
    channel_id: str
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None
    status: str
    max_participants: int | None = None
    runtime: SessionRuntime = Field(default_factory=SessionRuntime)
    post_id: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    @field_serializer("created_at", "started_at", "stopped_at")
    @classmethod
    def serialize_datetime(cls, v: datetime | None) -> str | None:
        return serialize_optional_utc_datetime(v)


class ListSessionsOut(BaseModel):
    sessions: list[SessionOut]
    next_cursor: str | None = None


class EndSessionOut(BaseModel):
    session_id: str = Field(description="Session ID of the ended session")
    room_id: str = Field(description="Room ID of the ended session")
    status: str = Field(description="Final session status")


class GetPlaybackUrlOut(BaseModel):
    playback_url: str = Field(description="HLS playback URL (live or VOD)")
    is_live: bool = Field(description="Whether the stream is currently live")
