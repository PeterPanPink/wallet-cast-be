"""Transcript pipeline for persisting/translating/publishing captions.

This module isolates transcript handling from any particular LiveKit agent/session,
so callers can attach participant context per transcript (e.g. multi-participant rooms).
"""

from __future__ import annotations

import time

from livekit import rtc
from livekit.agents import stt
from loguru import logger

from app.domain.livekit_agents.caption_agent.transcripts.handlers import (
    CompositeTranscriptHandler,
    TranscriptData,
    TranscriptHandler,
    TranscriptPersistenceHandler,
    TranscriptPublisher,
    TranscriptTranslator,
)


class TranscriptPipeline:
    """Builds and executes the transcript handler chain for final transcripts."""

    def __init__(
        self,
        *,
        session_id: str,
        room_id: str,
        handler: TranscriptHandler,
    ) -> None:
        self._session_id = session_id
        self._room_id = room_id
        self._handler = handler

    @classmethod
    def create_default(
        cls,
        *,
        session_id: str,
        room_id: str,
        room: rtc.Room | None,
        translation_languages: list[str] | None = None,
    ) -> TranscriptPipeline:
        publisher = TranscriptPublisher(room=room)
        handler = CompositeTranscriptHandler(
            handlers=[
                TranscriptTranslator(target_languages=translation_languages),
                TranscriptPersistenceHandler(),
                publisher,
            ]
        )
        return cls(session_id=session_id, room_id=room_id, handler=handler)

    async def handle_final_speech(
        self,
        *,
        participant_identity: str,
        speech: stt.SpeechData,
    ) -> None:
        """Convert STT SpeechData into TranscriptData and run the handler chain."""
        end = time.time()
        duration = speech.end_time
        start = end - duration

        if not participant_identity:
            participant_identity = "unknown"

        logger.info(
            f"📝 FINAL | Speaker: {participant_identity} | "
            f"Text: '{speech.text}' | Duration: {duration:.2f}s"
        )

        data = TranscriptData(
            session_id=self._session_id,
            room_id=self._room_id,
            participant_identity=participant_identity,
            text=speech.text,
            confidence=speech.confidence,
            start_time=start,
            end_time=end,
            duration=duration,
            language=speech.language,
            speaker_id=speech.speaker_id,
        )
        await self._handler.handle(data)
