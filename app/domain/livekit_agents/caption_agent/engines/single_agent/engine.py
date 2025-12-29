"""Single-agent caption engine (one job handles all participants)."""

from __future__ import annotations

from collections.abc import Mapping

from livekit import rtc

from app.domain.livekit_agents.caption_agent.engines.base import CaptionEngine
from app.domain.livekit_agents.caption_agent.engines.single_agent.transcriber import (
    RoomCaptionTranscriber,
)
from app.domain.livekit_agents.caption_agent.stt.config import SttConfigType


class SingleAgentCaptionEngine(CaptionEngine):
    def __init__(
        self,
        *,
        room: rtc.Room,
        session_id: str,
        room_id: str,
        translation_languages: list[str] | None,
        speaker_configs: Mapping[str, SttConfigType] | None,
        default_stt: SttConfigType,
    ) -> None:
        self._transcriber = RoomCaptionTranscriber(
            room=room,
            session_id=session_id,
            room_id=room_id,
            translation_languages=translation_languages,
            speaker_configs=speaker_configs,
            default_stt=default_stt,
        )

    def start(self) -> None:
        self._transcriber.start()

    def handle_existing(self) -> None:
        self._transcriber.handle_existing_tracks()

    async def aclose(self) -> None:
        await self._transcriber.aclose()
