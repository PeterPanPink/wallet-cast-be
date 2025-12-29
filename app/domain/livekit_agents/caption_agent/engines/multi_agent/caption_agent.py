"""Caption agent for LiveKit speech-to-text transcription.

This module provides the CaptionAgent class that handles STT processing
for a single participant. Transcript processing (persistence, translation,
publishing) is delegated to composable handlers following SRP.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterable
from typing import TYPE_CHECKING

from livekit import rtc
from livekit.agents import Agent, ModelSettings, stt, vad
from livekit.plugins import silero
from loguru import logger

from app.domain.livekit_agents.caption_agent.stt.config import (
    DEFAULT_STT_MODEL,
    CustomSttConfig,
    SpeakerSttConfig,
    SttConfigType,
)
from app.domain.livekit_agents.caption_agent.stt.processor import SttProcessor
from app.domain.livekit_agents.caption_agent.transcripts.handlers import (
    CompositeTranscriptHandler,
    TranscriptData,
    TranscriptPersistenceHandler,
    TranscriptPublisher,
    TranscriptTranslator,
)

if TYPE_CHECKING:
    pass


class CaptionAgent(Agent):
    """Caption agent for a single participant.

    This agent focuses solely on coordinating STT processing and delegating
    transcript handling to composable handlers. Responsibilities:
    - Configure and manage STT processing via SttProcessor
    - Convert speech events to TranscriptData
    - Delegate transcript handling to a pipeline of handlers

    The handler pipeline (translation → persistence → publishing) is
    configurable and follows the Chain of Responsibility pattern.
    """

    DEFAULT_TRANSLATION_LANGUAGES = ["es", "fr", "ja", "ko"]

    def __init__(
        self,
        session_id: str,
        room_id: str,
        participant_identity: str,
        stt_config: SttConfigType = DEFAULT_STT_MODEL,
        translation_languages: list[str] | None = None,
        vad: vad.VAD | None = None,
    ) -> None:
        """Initialize the caption agent.

        Args:
            session_id: Session ID for storing transcripts
            room_id: Room ID for transcript association
            participant_identity: The participant this agent transcribes
            stt_config: STT configuration - can be:
                - SpeakerSttConfig: Built-in OpenAI STT configuration
                - CustomSttConfig: Custom STT with optional VAD wrapping
                - stt.STT: Direct STT instance
                - str: Model descriptor string
            translation_languages: Target languages for translation
            vad: Pre-loaded VAD instance (shared to reduce resource usage)
        """
        self._vad_instance = vad or silero.VAD.load()
        self._custom_stt_config: CustomSttConfig | None = None

        # Parse STT configuration
        if isinstance(stt_config, CustomSttConfig):
            self._custom_stt_config = stt_config
            stt_model = None  # Custom STT bypasses Agent's built-in STT
        elif isinstance(stt_config, SpeakerSttConfig):
            stt_model = stt_config.to_stt_instance()
        elif isinstance(stt_config, stt.STT):
            stt_model = stt_config
        else:
            stt_model = stt_config  # str descriptor

        super().__init__(
            instructions="",
            stt=stt_model,
            llm=None,
            tts=None,
            vad=self._vad_instance,
        )

        self.session_id = session_id
        self.room_id = room_id
        self.participant_identity = participant_identity
        self.translation_languages = translation_languages or self.DEFAULT_TRANSLATION_LANGUAGES

        # Initialize components
        self._stt_processor = SttProcessor(
            custom_stt_config=self._custom_stt_config,
            vad_instance=self._vad_instance,
        )
        self._publisher: TranscriptPublisher | None = None
        self._transcript_handler = self._create_handler_pipeline()

    def _create_handler_pipeline(self) -> CompositeTranscriptHandler:
        """Create the transcript processing pipeline.

        Order matters: translate first, then persist (with translations),
        then publish to room.

        Returns:
            Configured composite handler with all processors
        """
        self._publisher = TranscriptPublisher()

        return CompositeTranscriptHandler(
            handlers=[
                TranscriptTranslator(target_languages=self.translation_languages),
                TranscriptPersistenceHandler(),
                self._publisher,
            ]
        )

    def set_room(self, room: rtc.Room) -> None:
        """Set the room for publishing data.

        Args:
            room: The LiveKit room instance
        """
        if self._publisher is None:
            logger.warning(
                "CaptionAgent publisher is not initialized; captions will not publish to data channel"
            )
            return
        self._publisher.set_room(room)

    async def stt_node(
        self, audio: AsyncIterable[rtc.AudioFrame], model_settings: ModelSettings
    ) -> AsyncIterable[stt.SpeechEvent | str]:
        """Custom STT node to intercept and process STT events.

        Supports two modes:
        1. Built-in STT: Delegates to Agent.default.stt_node() for standard processing
        2. Custom STT: Uses standalone streaming with push_frame/async iteration pattern
        """
        return self._stt_processor.process_stream(self, audio, model_settings)

    async def _on_stt_event(self, event: stt.SpeechEvent) -> None:
        """Handle a speech event from STT processor.

        Args:
            event: The speech event to process
        """
        if event.type == stt.SpeechEventType.FINAL_TRANSCRIPT and event.alternatives:
            speech_data = event.alternatives[0]
            if speech_data.text.strip():
                await self._process_final_transcript(speech_data)
        elif event.type == stt.SpeechEventType.INTERIM_TRANSCRIPT and event.alternatives:
            logger.debug(f"📝 INTERIM: '{event.alternatives[0].text[:50]}...'")

    async def _process_final_transcript(self, speech_data: stt.SpeechData) -> None:
        """Convert speech data to TranscriptData and delegate to handlers.

        Args:
            speech_data: The speech data from STT
        """
        end = time.time()
        duration = speech_data.end_time
        start = end - duration

        logger.info(
            f"📝 FINAL | Speaker: {self.participant_identity} | "
            f"Text: '{speech_data.text}' | Duration: {duration:.2f}s"
        )

        try:
            transcript_data = TranscriptData(
                session_id=self.session_id,
                room_id=self.room_id,
                participant_identity=self.participant_identity,
                text=speech_data.text,
                confidence=speech_data.confidence,
                start_time=start,
                end_time=end,
                duration=duration,
                language=speech_data.language,
                speaker_id=speech_data.speaker_id,
            )
            await self._transcript_handler.handle(transcript_data)
        except Exception as exc:
            logger.exception(f"Failed to process transcript: {exc}")

    async def on_enter(self) -> None:
        """Called when the agent enters the session."""
        # Set up the STT processor callback
        self._stt_processor.set_event_callback(self._on_stt_event)
        logger.info(f"CaptionAgent entered session for speaker '{self.participant_identity}'")
