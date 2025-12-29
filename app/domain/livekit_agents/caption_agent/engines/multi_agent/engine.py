"""Multi-agent caption engine (one agent session per participant)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.domain.livekit_agents.caption_agent.engines.base import CaptionEngine
from app.domain.livekit_agents.caption_agent.engines.multi_agent.manager import (
    MultiSpeakerCaptionManager,
)
from app.domain.livekit_agents.caption_agent.stt.config import DEFAULT_STT_MODEL, SttConfigType


class MultiAgentCaptionEngine(CaptionEngine):
    def __init__(
        self,
        *,
        ctx: JobContext,
        session_id: str,
        room_id: str,
        translation_languages: list[str] | None,
        speaker_configs: Mapping[str, SttConfigType] | None,
        default_stt: SttConfigType = DEFAULT_STT_MODEL,
    ) -> None:
        self._manager = MultiSpeakerCaptionManager(
            ctx=ctx,
            session_id=session_id,
            room_id=room_id,
            translation_languages=translation_languages,
            speaker_configs=speaker_configs,
            default_stt=default_stt,
        )

    def start(self) -> None:
        self._manager.start()

    def handle_existing(self) -> None:
        self._manager.handle_existing_participants()

    async def aclose(self) -> None:
        await self._manager.aclose()


if TYPE_CHECKING:
    from livekit.agents import JobContext
