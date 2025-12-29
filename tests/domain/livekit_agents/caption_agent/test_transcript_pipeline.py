"""Tests for TranscriptPipeline participant attribution."""

import pytest
from livekit.agents import stt

from app.domain.livekit_agents.caption_agent.transcripts.handlers import (
    TranscriptData,
    TranscriptHandler,
)
from app.domain.livekit_agents.caption_agent.transcripts.pipeline import TranscriptPipeline


class _CaptureHandler(TranscriptHandler):
    def __init__(self) -> None:
        self.items: list[TranscriptData] = []

    async def handle(self, data: TranscriptData) -> TranscriptData:  # type: ignore[override]
        self.items.append(data)
        return data


class TestTranscriptPipeline:
    @pytest.mark.asyncio
    async def test_attaches_participant_identity_per_transcript(self) -> None:
        handler = _CaptureHandler()
        pipeline = TranscriptPipeline(session_id="sess_1", room_id="room_1", handler=handler)

        await pipeline.handle_final_speech(
            participant_identity="alice",
            speech=stt.SpeechData(language="en", text="hello", end_time=1.2, confidence=0.9),
        )

        assert handler.items[0].participant_identity == "alice"

    @pytest.mark.asyncio
    async def test_defaults_empty_identity_to_unknown(self) -> None:
        handler = _CaptureHandler()
        pipeline = TranscriptPipeline(session_id="sess_1", room_id="room_1", handler=handler)

        await pipeline.handle_final_speech(
            participant_identity="",
            speech=stt.SpeechData(language="en", text="hello", end_time=1.2, confidence=0.9),
        )

        assert handler.items[0].participant_identity == "unknown"
