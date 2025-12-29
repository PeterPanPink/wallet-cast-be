"""Caption engine orchestration and mode selection."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any

from livekit.agents import JobContext
from loguru import logger

from app.domain.livekit_agents.caption_agent.engines.base import CaptionEngine
from app.domain.livekit_agents.caption_agent.engines.multi_agent.engine import (
    MultiAgentCaptionEngine,
)
from app.domain.livekit_agents.caption_agent.engines.single_agent.engine import (
    SingleAgentCaptionEngine,
)
from app.domain.livekit_agents.caption_agent.stt.config import (
    DEFAULT_STT_MODEL,
    SpeakerSttConfig,
    SttConfigType,
    parse_speaker_stt_descriptor,
)


class CaptionEngineMode(str, Enum):
    SINGLE_AGENT = "single_agent"
    MULTI_AGENT = "multi_agent"


def parse_job_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        logger.warning("Invalid job metadata JSON; continuing with defaults")
        return {}


def _parse_stt_config(raw: object) -> SttConfigType:
    if isinstance(raw, dict):
        return SpeakerSttConfig(**raw)
    if isinstance(raw, str):
        parsed = parse_speaker_stt_descriptor(raw)
        return parsed or raw
    return DEFAULT_STT_MODEL


def _parse_speaker_configs(raw: object) -> dict[str, SpeakerSttConfig]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, SpeakerSttConfig] = {}
    for identity, config in raw.items():
        if isinstance(identity, str) and isinstance(config, dict):
            out[identity] = SpeakerSttConfig(**config)
    return out


def select_engine_mode(metadata: dict[str, Any]) -> CaptionEngineMode:
    raw = (
        metadata.get("engine_mode")
        or metadata.get("mode")
        or metadata.get("engine")
        or metadata.get("caption_engine")
    )
    if isinstance(raw, str):
        raw = raw.strip().lower()
        if raw in {CaptionEngineMode.MULTI_AGENT.value, "multi"}:
            return CaptionEngineMode.MULTI_AGENT
        if raw in {CaptionEngineMode.SINGLE_AGENT.value, "single"}:
            return CaptionEngineMode.SINGLE_AGENT
    return CaptionEngineMode.SINGLE_AGENT


def build_caption_engine(ctx: JobContext, metadata: dict[str, Any]) -> CaptionEngine:
    session_id = metadata.get("session_id", "unknown")
    translation_languages = metadata.get("translation_languages")
    if translation_languages is not None and not isinstance(translation_languages, list):
        translation_languages = None

    default_stt = _parse_stt_config(metadata.get("default_stt"))
    speaker_configs = _parse_speaker_configs(metadata.get("speaker_configs"))
    room_id = ctx.room.name

    mode = select_engine_mode(metadata)
    logger.info(f"Caption engine mode: {mode.value}")

    if mode == CaptionEngineMode.MULTI_AGENT:
        return MultiAgentCaptionEngine(
            ctx=ctx,
            session_id=session_id,
            room_id=room_id,
            translation_languages=translation_languages,
            speaker_configs=speaker_configs,
            default_stt=default_stt,
        )

    return SingleAgentCaptionEngine(
        room=ctx.room,
        session_id=session_id,
        room_id=room_id,
        translation_languages=translation_languages,
        speaker_configs=speaker_configs,
        default_stt=default_stt,
    )
