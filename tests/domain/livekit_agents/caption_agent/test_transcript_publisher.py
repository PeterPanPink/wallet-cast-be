"""Tests for publishing live transcripts to the LiveKit data channel."""

import json
from unittest.mock import AsyncMock

import pytest

from app.domain.livekit_agents.caption_agent.transcripts.handlers import (
    TranscriptData,
    TranscriptPublisher,
)


class _FakeLocalParticipant:
    def __init__(self) -> None:
        self.publish_data = AsyncMock()


class _FalsyRoom:
    """Room object that is valid but evaluates to False."""

    def __init__(self) -> None:
        self.local_participant = _FakeLocalParticipant()

    def __len__(self) -> int:
        return 0


class TestTranscriptPublisher:
    @pytest.mark.asyncio
    async def test_publishes_even_when_room_is_falsy(self) -> None:
        publisher = TranscriptPublisher()
        room = _FalsyRoom()
        publisher.set_room(room)  # type: ignore[arg-type]

        data = TranscriptData(
            session_id="sess_1",
            room_id="room_1",
            participant_identity="user_1",
            text="hello",
            language="en",
            translations={"es": "hola"},
        )

        await publisher.handle(data)

        room.local_participant.publish_data.assert_called_once()
        args, kwargs = room.local_participant.publish_data.call_args

        assert kwargs["topic"] == TranscriptPublisher.TOPIC
        payload = json.loads(args[0].decode("utf-8"))
        assert payload["text"] == "hello"
        assert payload["language"] == "en"
        assert payload["participant_identity"] == "user_1"
        assert payload["translations"] == {"es": "hola"}

    @pytest.mark.asyncio
    async def test_no_publish_when_room_not_set(self) -> None:
        publisher = TranscriptPublisher(room=None)
        data = TranscriptData(
            session_id="sess_1",
            room_id="room_1",
            participant_identity="user_1",
            text="hello",
        )

        result = await publisher.handle(data)
        assert result is data
