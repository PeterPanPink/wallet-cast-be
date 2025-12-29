"""Regression tests for CaptionAgent data channel wiring."""

from unittest.mock import AsyncMock

import pytest

from app.domain.livekit_agents.caption_agent.engines.multi_agent.caption_agent import CaptionAgent
from app.domain.livekit_agents.caption_agent.transcripts.handlers import TranscriptData


class _FakeLocalParticipant:
    def __init__(self) -> None:
        self.publish_data = AsyncMock()


class _FakeRoom:
    def __init__(self) -> None:
        self.local_participant = _FakeLocalParticipant()


class TestCaptionAgentRoomWiring:
    @pytest.mark.asyncio
    async def test_set_room_wires_publisher(self) -> None:
        agent = CaptionAgent(
            session_id="sess_1",
            room_id="room_1",
            participant_identity="user_1",
            stt_config=object(),  # avoid loading real STT backends
            vad=object(),  # avoid loading silero VAD
        )
        assert agent._publisher is not None

        room = _FakeRoom()
        agent.set_room(room)  # type: ignore[arg-type]

        await agent._publisher.handle(
            TranscriptData(
                session_id="sess_1",
                room_id="room_1",
                participant_identity="user_1",
                text="hello",
            )
        )

        room.local_participant.publish_data.assert_called_once()
