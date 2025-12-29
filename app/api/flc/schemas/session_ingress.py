from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


class CreateRoomIn(BaseModel):
    """Request to create a LiveKit room."""

    session_id: str | None = Field(default=None, description="Session ID to create room for")
    room_id: str | None = Field(default=None, description="Room ID to create room for")
    metadata: str | None = Field(
        default=None, description="Optional JSON string containing room metadata"
    )
    empty_timeout: int = Field(
        default=300, description="Timeout in seconds before room closes when empty"
    )
    max_participants: int = Field(default=100, description="Maximum number of participants allowed")

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


class CreateRoomOut(BaseModel):
    """Response after creating a LiveKit room."""

    room_name: str = Field(description="Name of the created room")
    room_sid: str = Field(description="Server-assigned room SID")
    metadata: str | None = Field(default=None, description="Room metadata")
    max_participants: int = Field(description="Maximum number of participants allowed")


class DeleteRoomIn(BaseModel):
    """Request to delete a LiveKit room."""

    session_id: str | None = Field(default=None, description="Session ID to delete room for")
    room_id: str | None = Field(default=None, description="Room ID to delete")

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


class DeleteRoomOut(BaseModel):
    """Response after deleting a LiveKit room."""

    room_name: str = Field(description="Name of the deleted room")
    deleted: bool = Field(default=True, description="Whether the room was deleted")


class GetHostTokenIn(BaseModel):
    """Request to generate a host access token."""

    session_id: str | None = Field(default=None, description="Session ID to grant access to")
    room_id: str | None = Field(default=None, description="Room ID to grant access to")
    metadata: str | None = Field(default=None, description="Custom metadata string")

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


class GetGuestTokenIn(BaseModel):
    """Request to generate a guest/viewer access token."""

    display_name: str = Field(description="Display name for the guest participant")
    session_id: str | None = Field(default=None, description="Session ID to grant access to")
    room_id: str | None = Field(default=None, description="Room ID to grant access to")
    metadata: str | None = Field(default=None, description="Custom metadata string")
    can_publish: bool = Field(default=True, description="Whether guest can publish tracks")

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


class GetRecorderTokenIn(BaseModel):
    """Request to generate a recorder access token to join and record the live."""

    room_id: str = Field(description="Room ID to join for recording")
    identity: str | None = Field(
        default=None, description="Custom identity for the recorder participant"
    )
    display_name: str | None = Field(default=None, description="Display name for the recorder")
    metadata: str | None = Field(default=None, description="Custom metadata string")


class AccessTokenOut(BaseModel):
    """Response containing an access token."""

    token: str = Field(description="JWT access token")
    token_ttl: int = Field(default=3600, description="Token TTL in seconds")
    token_issued_at: datetime = Field(description="Token issue timestamp")
    token_expires_at: datetime = Field(description="Token expiration timestamp")
    identity: str = Field(description="Participant identity")
    room_name: str = Field(description="Room name")
    livekit_url: str = Field(description="LiveKit server WebSocket URL")


# ==================== CAPTION/INTERPRETATION SCHEMAS ====================


class EnableCaptionRequest(BaseModel):
    """Request to enable captions with translations for a session."""

    session_id: str | None = Field(default=None, description="Session ID to enable captions for")
    room_id: str | None = Field(default=None, description="Room ID to enable captions for")
    translation_languages: list[str] = Field(
        default_factory=lambda: ["Spanish", "French", "Japanese", "Korean"],
        description="Target languages for translation (always enabled with translations)",
    )

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


class DisableCaptionRequest(BaseModel):
    """Request to disable captions for a session."""

    session_id: str | None = Field(default=None, description="Session ID to disable captions for")
    room_id: str | None = Field(default=None, description="Room ID to disable captions for")

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


class CaptionStatusRequest(BaseModel):
    """Request to check caption status."""

    session_id: str | None = Field(default=None, description="Session ID to check status for")
    room_id: str | None = Field(default=None, description="Room ID to check status for")

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


class EnableCaptionResponse(BaseModel):
    """Response when captions are enabled."""

    session_id: str
    status: str
    job_id: str | None = None


class DisableCaptionResponse(BaseModel):
    """Response when captions are disabled."""

    session_id: str
    status: str
    job_id: str | None = None


class CaptionStatusResponse(BaseModel):
    """Response with caption status."""

    session_id: str
    enabled: bool
    status: str | None = None


class UpdateParticipantNameIn(BaseModel):
    """Request to update a participant's display name."""

    session_id: str | None = Field(default=None, description="Session ID where the participant is")
    room_id: str | None = Field(default=None, description="Room ID where the participant is")
    identity: str = Field(min_length=1, description="Identity of the participant to update")
    name: str = Field(min_length=1, description="New display name for the participant")

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


class UpdateParticipantNameOut(BaseModel):
    """Response after updating a participant's display name."""

    identity: str = Field(description="Participant identity")
    name: str = Field(description="Updated display name")
    sid: str = Field(description="Participant SID")


# ==================== PARTICIPANT LANGUAGE UPDATE SCHEMAS ====================


class UpdateParticipantLanguageRequest(BaseModel):
    """Request to update a participant's original language for STT processing.

    This allows a participant to change their spoken language while the caption
    agent is running. The STT will restart with the new language configuration
    for this participant only, without affecting other participants.
    """

    session_id: str | None = Field(default=None, description="Session ID where the participant is")
    room_id: str | None = Field(default=None, description="Room ID where the participant is")
    participant_identity: str = Field(
        description="Identity of the participant whose language is being updated"
    )
    language: str = Field(
        description="New language code for STT (e.g., 'en', 'zh', 'es', 'fr', 'ja')"
    )

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


class UpdateParticipantLanguageResponse(BaseModel):
    """Response after updating a participant's language."""

    session_id: str = Field(description="Session ID")
    participant_identity: str = Field(description="Participant identity")
    language: str = Field(description="Updated language code")
    status: str = Field(description="Status of the update (e.g., 'updated', 'pending')")


class GetInviteLinkIn(BaseModel):
    """Request to get invite link for a session."""

    session_id: str | None = Field(default=None, description="Session ID to get invite link for")
    room_id: str | None = Field(default=None, description="Room ID to get invite link for")

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


class GetInviteLinkOut(BaseModel):
    """Response containing invite link."""

    invite_link: str = Field(description="Invite link for the session")
