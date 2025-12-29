"""LiveKit webhook event schemas.

Pydantic models for LiveKit webhook events based on the LiveKit protocol.

References:
- https://docs.livekit.io/home/server/webhooks/
- livekit.protocol.webhook.WebhookEvent
- livekit.protocol.models (Room, ParticipantInfo, TrackInfo, EgressInfo, IngressInfo)
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ParticipantState(str, Enum):
    """Participant connection state."""

    JOINING = "JOINING"
    JOINED = "JOINED"
    ACTIVE = "ACTIVE"
    DISCONNECTED = "DISCONNECTED"


class ParticipantKind(str, Enum):
    """Participant kind/role."""

    STANDARD = "STANDARD"
    INGRESS = "INGRESS"
    EGRESS = "EGRESS"
    SIP = "SIP"
    AGENT = "AGENT"


class TrackType(str, Enum):
    """Track media type."""

    AUDIO = "AUDIO"
    VIDEO = "VIDEO"
    DATA = "DATA"


class TrackSource(str, Enum):
    """Track source type."""

    UNKNOWN = "UNKNOWN"
    CAMERA = "CAMERA"
    MICROPHONE = "MICROPHONE"
    SCREEN_SHARE = "SCREEN_SHARE"
    SCREEN_SHARE_AUDIO = "SCREEN_SHARE_AUDIO"


class VideoQuality(str, Enum):
    """Video quality level."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    OFF = "OFF"


class DisconnectReason(str, Enum):
    """Reason for participant disconnection."""

    UNKNOWN_REASON = "UNKNOWN_REASON"
    CLIENT_INITIATED = "CLIENT_INITIATED"
    DUPLICATE_IDENTITY = "DUPLICATE_IDENTITY"
    SERVER_SHUTDOWN = "SERVER_SHUTDOWN"
    PARTICIPANT_REMOVED = "PARTICIPANT_REMOVED"
    ROOM_DELETED = "ROOM_DELETED"
    STATE_MISMATCH = "STATE_MISMATCH"
    JOIN_FAILURE = "JOIN_FAILURE"
    MIGRATION = "MIGRATION"
    SIGNAL_CLOSE = "SIGNAL_CLOSE"
    ROOM_CLOSED = "ROOM_CLOSED"
    USER_UNAVAILABLE = "USER_UNAVAILABLE"
    USER_REJECTED = "USER_REJECTED"
    SIP_TRUNK_FAILURE = "SIP_TRUNK_FAILURE"
    CONNECTION_TIMEOUT = "CONNECTION_TIMEOUT"
    MEDIA_FAILURE = "MEDIA_FAILURE"


class EgressStatus(str, Enum):
    """Egress recording status."""

    EGRESS_STARTING = "EGRESS_STARTING"
    EGRESS_ACTIVE = "EGRESS_ACTIVE"
    EGRESS_ENDING = "EGRESS_ENDING"
    EGRESS_COMPLETE = "EGRESS_COMPLETE"
    EGRESS_FAILED = "EGRESS_FAILED"
    EGRESS_ABORTED = "EGRESS_ABORTED"
    EGRESS_LIMIT_REACHED = "EGRESS_LIMIT_REACHED"


class IngressState(str, Enum):
    """Ingress stream state."""

    ENDPOINT_INACTIVE = "ENDPOINT_INACTIVE"
    ENDPOINT_BUFFERING = "ENDPOINT_BUFFERING"
    ENDPOINT_PUBLISHING = "ENDPOINT_PUBLISHING"
    ENDPOINT_ERROR = "ENDPOINT_ERROR"
    ENDPOINT_COMPLETE = "ENDPOINT_COMPLETE"


# Base models for nested objects


class VideoLayer(BaseModel):
    """Video layer information for simulcast."""

    quality: VideoQuality | None = Field(None, description="Video quality level")
    width: int = Field(..., description="Video width in pixels")
    height: int = Field(..., description="Video height in pixels")
    bitrate: int = Field(..., description="Target bitrate in bps")
    ssrc: int | None = Field(None, description="RTP SSRC")
    spatial_layer: int | None = Field(None, alias="spatialLayer", description="Spatial layer index")
    rid: str | None = Field(None, description="RTP stream ID (rid)")


class TrackInfo(BaseModel):
    """Track information."""

    sid: str = Field(..., description="Track server ID")
    type: TrackType = Field(TrackType.AUDIO, description="Track type (audio/video/data)")
    name: str | None = Field(None, description="Track name")
    muted: bool = Field(False, description="Whether track is muted")
    width: int | None = Field(None, description="Video width (for video tracks)")
    height: int | None = Field(None, description="Video height (for video tracks)")
    simulcast: bool = Field(False, description="Whether simulcast is enabled")
    source: TrackSource = Field(TrackSource.UNKNOWN, description="Track source type")
    layers: list[VideoLayer] | None = Field(None, description="Video layers (for simulcast)")
    mime_type: str | None = Field(None, alias="mimeType", description="Track MIME type")
    mid: str | None = Field(None, description="Media stream ID")
    stream: str | None = Field(None, description="Stream ID")


class ParticipantPermission(BaseModel):
    """Participant permissions."""

    can_subscribe: bool = Field(True, alias="canSubscribe", description="Can subscribe to tracks")
    can_publish: bool = Field(True, alias="canPublish", description="Can publish tracks")
    can_publish_data: bool = Field(True, alias="canPublishData", description="Can publish data")
    can_publish_sources: list[TrackSource] | None = Field(
        None, alias="canPublishSources", description="Allowed publish sources"
    )
    hidden: bool = Field(False, description="Whether participant is hidden")
    can_update_metadata: bool = Field(
        True, alias="canUpdateMetadata", description="Can update metadata"
    )
    can_subscribe_metrics: bool = Field(
        False, alias="canSubscribeMetrics", description="Can subscribe to metrics"
    )


class ParticipantInfo(BaseModel):
    """Participant information."""

    sid: str = Field(..., description="Participant server ID")
    identity: str = Field(..., description="Participant identity (unique ID)")
    state: ParticipantState | None = Field(None, description="Participant state")
    name: str | None = Field(None, description="Participant display name")
    metadata: str | None = Field(None, description="Participant metadata (JSON)")
    joined_at: int | None = Field(None, alias="joinedAt", description="Join timestamp (seconds)")
    joined_at_ms: int | None = Field(
        None, alias="joinedAtMs", description="Join timestamp (milliseconds)"
    )
    tracks: list[TrackInfo] | None = Field(None, description="Published tracks")
    version: int | None = Field(None, description="Protocol version")
    permission: ParticipantPermission | None = Field(None, description="Participant permissions")
    region: str | None = Field(None, description="Participant region")
    is_publisher: bool | None = Field(
        None, alias="isPublisher", description="Whether participant is publishing"
    )
    kind: ParticipantKind | None = Field(None, description="Participant kind")
    attributes: dict[str, str] | None = Field(None, description="Custom attributes")
    disconnect_reason: DisconnectReason | None = Field(
        None, alias="disconnectReason", description="Reason for disconnect"
    )


class Room(BaseModel):
    """Room information."""

    sid: str = Field(..., description="Room server ID")
    name: str = Field(..., description="Room name")
    empty_timeout: int | None = Field(
        None, alias="emptyTimeout", description="Empty room timeout (seconds)"
    )
    departure_timeout: int | None = Field(
        None, alias="departureTimeout", description="Departure timeout (seconds)"
    )
    max_participants: int | None = Field(
        None, alias="maxParticipants", description="Maximum participants"
    )
    creation_time: int | None = Field(
        None, alias="creationTime", description="Creation timestamp (seconds)"
    )
    creation_time_ms: int | None = Field(
        None, alias="creationTimeMs", description="Creation timestamp (milliseconds)"
    )
    metadata: str | None = Field(None, description="Room metadata (JSON)")
    num_participants: int | None = Field(
        None, alias="numParticipants", description="Current participant count"
    )
    num_publishers: int | None = Field(
        None, alias="numPublishers", description="Current publisher count"
    )
    active_recording: bool | None = Field(
        None, alias="activeRecording", description="Whether recording is active"
    )


class EgressInfo(BaseModel):
    """Egress recording information."""

    egress_id: str = Field(..., alias="egressId", description="Egress server ID")
    room_id: str | None = Field(None, alias="roomId", description="Room ID")
    room_name: str | None = Field(None, alias="roomName", description="Room name")
    status: EgressStatus = Field(..., description="Egress status")
    started_at: int | None = Field(
        None, alias="startedAt", description="Start timestamp (milliseconds)"
    )
    ended_at: int | None = Field(None, alias="endedAt", description="End timestamp (milliseconds)")
    updated_at: int | None = Field(
        None, alias="updatedAt", description="Update timestamp (milliseconds)"
    )
    error: str | None = Field(None, description="Error message if failed")
    stream_results: list[dict[str, str]] | None = Field(
        None, alias="streamResults", description="Stream output results"
    )
    file_results: list[dict[str, str]] | None = Field(
        None, alias="fileResults", description="File output results"
    )
    segment_results: list[dict[str, str]] | None = Field(
        None, alias="segmentResults", description="Segment output results"
    )


class IngressInfo(BaseModel):
    """Ingress stream information."""

    ingress_id: str = Field(..., alias="ingressId", description="Ingress server ID")
    name: str = Field(..., description="Ingress name")
    stream_key: str | None = Field(None, alias="streamKey", description="Stream key for RTMP/WHIP")
    url: str | None = Field(None, description="Ingress URL")
    room_name: str | None = Field(None, alias="roomName", description="Room name")
    participant_identity: str | None = Field(
        None, alias="participantIdentity", description="Participant identity"
    )
    participant_name: str | None = Field(
        None, alias="participantName", description="Participant name"
    )
    state: IngressState | None = Field(None, description="Ingress state")
    error: str | None = Field(None, description="Error message if failed")


# Webhook event types


class RoomStartedEvent(BaseModel):
    """Room started event - first participant joined."""

    event: Literal["room_started"] = "room_started"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")


class RoomFinishedEvent(BaseModel):
    """Room finished event - all participants left and timeout expired."""

    event: Literal["room_finished"] = "room_finished"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")


class ParticipantJoinedEvent(BaseModel):
    """Participant joined event."""

    event: Literal["participant_joined"] = "participant_joined"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")
    participant: ParticipantInfo = Field(..., description="Participant information")


class ParticipantLeftEvent(BaseModel):
    """Participant left event."""

    event: Literal["participant_left"] = "participant_left"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")
    participant: ParticipantInfo = Field(..., description="Participant information")


class ParticipantConnectionAbortedEvent(BaseModel):
    """Participant connection aborted event."""

    event: Literal["participant_connection_aborted"] = "participant_connection_aborted"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")
    participant: ParticipantInfo = Field(..., description="Participant information")


class TrackPublishedEvent(BaseModel):
    """Track published event."""

    event: Literal["track_published"] = "track_published"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")
    participant: ParticipantInfo = Field(..., description="Participant information")
    track: TrackInfo = Field(..., description="Track information")


class TrackUnpublishedEvent(BaseModel):
    """Track unpublished event."""

    event: Literal["track_unpublished"] = "track_unpublished"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    room: Room = Field(..., description="Room information")
    participant: ParticipantInfo = Field(..., description="Participant information")
    track: TrackInfo = Field(..., description="Track information")


class EgressStartedEvent(BaseModel):
    """Egress started event."""

    event: Literal["egress_started"] = "egress_started"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    egress_info: EgressInfo = Field(..., alias="egressInfo", description="Egress information")


class EgressUpdatedEvent(BaseModel):
    """Egress updated event."""

    event: Literal["egress_updated"] = "egress_updated"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    egress_info: EgressInfo = Field(..., alias="egressInfo", description="Egress information")


class EgressEndedEvent(BaseModel):
    """Egress ended event."""

    event: Literal["egress_ended"] = "egress_ended"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    egress_info: EgressInfo = Field(..., alias="egressInfo", description="Egress information")


class IngressStartedEvent(BaseModel):
    """Ingress started event."""

    event: Literal["ingress_started"] = "ingress_started"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    ingress_info: IngressInfo = Field(..., alias="ingressInfo", description="Ingress information")


class IngressEndedEvent(BaseModel):
    """Ingress ended event."""

    event: Literal["ingress_ended"] = "ingress_ended"
    id: str = Field(..., description="Event UUID")
    created_at: int = Field(..., alias="createdAt", description="Event timestamp (seconds)")
    ingress_info: IngressInfo = Field(..., alias="ingressInfo", description="Ingress information")


# Union type for all webhook events
LiveKitWebhookEvent = (
    RoomStartedEvent
    | RoomFinishedEvent
    | ParticipantJoinedEvent
    | ParticipantLeftEvent
    | ParticipantConnectionAbortedEvent
    | TrackPublishedEvent
    | TrackUnpublishedEvent
    | EgressStartedEvent
    | EgressUpdatedEvent
    | EgressEndedEvent
    | IngressStartedEvent
    | IngressEndedEvent
)
