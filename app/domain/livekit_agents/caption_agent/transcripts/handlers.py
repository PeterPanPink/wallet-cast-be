"""Transcript handlers for caption processing.

This module provides composable handlers for transcript processing,
following the Single Responsibility Principle. Each handler focuses
on a specific aspect of transcript processing.

Classes:
    - TranscriptData: Data class for transcript information
    - TranscriptHandler: Protocol for transcript event handlers
    - TranscriptPersistenceHandler: Saves transcripts to MongoDB
    - TranscriptPublisher: Publishes transcripts to room data channel
    - TranscriptTranslator: Translates transcripts to target languages
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from livekit import rtc
from loguru import logger

from app.shared.storage.mongo import get_mongo_client
from app.schemas import Transcript
from app.schemas.init import init_beanie_odm
from app.services.integrations.translator_service import TranslatorService

if TYPE_CHECKING:
    pass

FLC_MONGO_LABEL = "flc_primary"


@dataclass
class TranscriptData:
    """Data class containing transcript information.

    This is the standardized format passed between handlers,
    decoupling them from LiveKit-specific types.
    """

    session_id: str
    room_id: str
    participant_identity: str
    text: str
    confidence: float | None = None
    start_time: float = 0.0
    end_time: float = 0.0
    duration: float = 0.0
    language: str | None = None
    speaker_id: str | None = None
    translations: dict[str, str] = field(default_factory=dict)


class TranscriptHandler(ABC):
    """Abstract base class for transcript event handlers.

    Handlers implement the Chain of Responsibility pattern,
    allowing multiple handlers to process transcript events.
    """

    @abstractmethod
    async def handle(self, data: TranscriptData) -> TranscriptData:
        """Handle a transcript event.

        Args:
            data: The transcript data to process

        Returns:
            The (potentially modified) transcript data for the next handler
        """


class TranscriptTranslator(TranscriptHandler):
    """Translates transcripts to configured target languages.

    This handler enriches TranscriptData with translations
    using the TranslatorService.
    """

    DEFAULT_LANGUAGES = ["es", "fr", "ja", "ko"]

    def __init__(self, target_languages: list[str] | None = None) -> None:
        """Initialize the translator handler.

        Args:
            target_languages: Languages to translate to (ISO 639-1 codes)
        """
        self._target_languages = target_languages or self.DEFAULT_LANGUAGES
        self._translator: TranslatorService | None = None
        self._initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazily initialize the TranslatorService."""
        if self._initialized:
            return

        try:
            self._translator = TranslatorService()
            self._initialized = True
        except Exception as exc:
            logger.warning(f"Failed to initialize TranslatorService: {exc}")
            self._initialized = True  # Don't retry on failure

    async def handle(self, data: TranscriptData) -> TranscriptData:
        """Translate the transcript text to target languages.

        Args:
            data: The transcript data to translate

        Returns:
            TranscriptData with translations populated
        """
        await self._ensure_initialized()

        if not self._translator or not self._target_languages:
            return data

        try:
            response = await self._translator.translate(
                text=data.text,
                target_languages=self._target_languages,
            )
            data.translations = response.translations
        except Exception as exc:
            logger.warning(f"Translation failed: {exc}")

        return data


class TranscriptPersistenceHandler(TranscriptHandler):
    """Persists transcripts to MongoDB using Beanie ODM.

    This handler saves transcript data to the database,
    creating a permanent record of all transcriptions.
    """

    def __init__(self) -> None:
        """Initialize the persistence handler."""
        self._beanie_initialized = False

    async def _ensure_initialized(self) -> None:
        """Lazily initialize Beanie ODM connection."""
        if self._beanie_initialized:
            return

        mongo_client = get_mongo_client(FLC_MONGO_LABEL)
        database = mongo_client.get_database()
        await init_beanie_odm(database)
        self._beanie_initialized = True
        logger.info("Beanie ODM initialized for TranscriptPersistenceHandler")

    async def handle(self, data: TranscriptData) -> TranscriptData:
        """Save the transcript to MongoDB.

        Args:
            data: The transcript data to persist

        Returns:
            The unchanged transcript data
        """
        await self._ensure_initialized()

        try:
            transcript = Transcript(
                session_id=data.session_id,
                room_id=data.room_id,
                text=data.text,
                confidence=data.confidence,
                start_time=data.start_time,
                end_time=data.end_time,
                duration=data.duration,
                language=data.language,
                speaker_id=data.speaker_id,
                participant_identity=data.participant_identity,
                translations=data.translations if data.translations else None,
            )
            await transcript.insert()
            logger.info(f"💾 Saved transcript: {transcript.id}")
        except Exception as exc:
            logger.exception(f"Failed to persist transcript: {exc}")

        return data


class TranscriptPublisher(TranscriptHandler):
    """Publishes live transcripts to room participants via data channel.

    This handler broadcasts transcript data to all room participants
    for real-time caption display.
    """

    TOPIC = "live-transcript"

    def __init__(self, room: rtc.Room | None = None) -> None:
        """Initialize the publisher handler.

        Args:
            room: The LiveKit room for publishing data
        """
        self._room = room

    def set_room(self, room: rtc.Room) -> None:
        """Set or update the room for publishing.

        Args:
            room: The LiveKit room instance
        """
        self._room = room

    async def handle(self, data: TranscriptData) -> TranscriptData:
        """Publish transcript to room participants.

        Args:
            data: The transcript data to publish

        Returns:
            The unchanged transcript data
        """
        # Don't use truthiness here: `rtc.Room` may implement `__len__` which can
        # make a valid room evaluate to False (e.g., before participants/tracks
        # are attached), causing captions to never publish.
        if self._room is None:
            logger.debug("Skipping transcript publish: room is not set")
            return data

        try:
            local_participant = getattr(self._room, "local_participant", None)
            if local_participant is None:
                logger.debug("Skipping transcript publish: local_participant is not available")
                return data

            payload = json.dumps(
                {
                    "text": data.text,
                    "language": data.language,
                    "translations": data.translations if data.translations else None,
                    "speaker_id": data.speaker_id,
                    "participant_identity": data.participant_identity,
                }
            ).encode("utf-8")

            # Use positional payload to be resilient across SDK versions where the
            # first parameter name may be `data` or `payload`.
            await local_participant.publish_data(payload, topic=self.TOPIC)
            logger.debug(f"📤 Published transcript for {data.participant_identity}")
        except Exception as exc:
            logger.exception(f"Failed to publish transcript: {exc}")

        return data


class CompositeTranscriptHandler(TranscriptHandler):
    """Composes multiple handlers into a processing pipeline.

    Handlers are executed in order, with each handler receiving
    the output from the previous handler.
    """

    def __init__(self, handlers: list[TranscriptHandler] | None = None) -> None:
        """Initialize the composite handler.

        Args:
            handlers: List of handlers to execute in order
        """
        self._handlers = handlers or []

    def add_handler(self, handler: TranscriptHandler) -> None:
        """Add a handler to the pipeline.

        Args:
            handler: The handler to add
        """
        self._handlers.append(handler)

    async def handle(self, data: TranscriptData) -> TranscriptData:
        """Execute all handlers in sequence.

        Args:
            data: The initial transcript data

        Returns:
            The transcript data after all handlers have processed it
        """
        for handler in self._handlers:
            data = await handler.handle(data)
        return data
