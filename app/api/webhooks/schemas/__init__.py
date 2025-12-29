"""Webhook schemas for external providers."""

from app.api.webhooks.schemas.livekit import (
    EgressEndedEvent,
    EgressStartedEvent,
    EgressUpdatedEvent,
    IngressEndedEvent,
    IngressStartedEvent,
    ParticipantConnectionAbortedEvent,
    ParticipantJoinedEvent,
    ParticipantLeftEvent,
    RoomFinishedEvent,
    RoomStartedEvent,
    TrackPublishedEvent,
    TrackUnpublishedEvent,
)
from app.api.webhooks.schemas.mux import (
    AssetCreatedEvent,
    AssetDeletedEvent,
    AssetErroredEvent,
    AssetReadyEvent,
    LiveStreamActiveEvent,
    LiveStreamCreatedEvent,
    LiveStreamDeletedEvent,
    LiveStreamDisconnectedEvent,
    LiveStreamIdleEvent,
    LiveStreamRecordingEvent,
    MuxEventType,
)

__all__ = [
    # Mux events
    "AssetCreatedEvent",
    "AssetDeletedEvent",
    "AssetErroredEvent",
    "AssetReadyEvent",
    # LiveKit events
    "EgressEndedEvent",
    "EgressStartedEvent",
    "EgressUpdatedEvent",
    "IngressEndedEvent",
    "IngressStartedEvent",
    "LiveStreamActiveEvent",
    "LiveStreamCreatedEvent",
    "LiveStreamDeletedEvent",
    "LiveStreamDisconnectedEvent",
    "LiveStreamIdleEvent",
    "LiveStreamRecordingEvent",
    "MuxEventType",
    "ParticipantConnectionAbortedEvent",
    "ParticipantJoinedEvent",
    "ParticipantLeftEvent",
    "RoomFinishedEvent",
    "RoomStartedEvent",
    "TrackPublishedEvent",
    "TrackUnpublishedEvent",
]
