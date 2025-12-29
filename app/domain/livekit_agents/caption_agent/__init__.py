"""Caption agent module (LiveKit Agents).

Top-level API:
- `CaptionAgentService`: dispatch caption jobs to rooms
- `CAPTION_AGENT_NAME`: the LiveKit agent name to dispatch

Internals are organized into subpackages:
- `engines`: pluggable caption engine implementations
- `stt`: STT configuration + helpers
- `transcripts`: transcript handlers + pipelines
- `delivery`: S3 uploader, etc.
"""

from app.domain.livekit_agents.caption_agent.delivery.s3_uploader import CaptionS3Uploader
from app.domain.livekit_agents.caption_agent.engines.base import CaptionEngine
from app.domain.livekit_agents.caption_agent.engines.multi_agent.caption_agent import CaptionAgent
from app.domain.livekit_agents.caption_agent.engines.multi_agent.engine import (
    MultiAgentCaptionEngine,
)
from app.domain.livekit_agents.caption_agent.engines.multi_agent.manager import (
    MultiSpeakerCaptionManager,
)
from app.domain.livekit_agents.caption_agent.engines.single_agent.engine import (
    SingleAgentCaptionEngine,
)
from app.domain.livekit_agents.caption_agent.engines.single_agent.transcriber import (
    RoomCaptionTranscriber,
)
from app.domain.livekit_agents.caption_agent.orchestrator import (
    CaptionEngineMode,
    build_caption_engine,
    parse_job_metadata,
    select_engine_mode,
)
from app.domain.livekit_agents.caption_agent.service import (
    CAPTION_AGENT_NAME,
    CaptionAgentParams,
    CaptionAgentService,
    initialize_beanie_for_worker,
)
from app.domain.livekit_agents.caption_agent.stt.config import (
    DEFAULT_STT_MODEL,
    CustomSttConfig,
    SpeakerSttConfig,
    SttConfigType,
    SttProvider,
    parse_speaker_stt_descriptor,
    resolve_stt_model,
)
from app.domain.livekit_agents.caption_agent.stt.processor import SttProcessor
from app.domain.livekit_agents.caption_agent.transcripts.handlers import (
    CompositeTranscriptHandler,
    TranscriptData,
    TranscriptHandler,
    TranscriptPersistenceHandler,
    TranscriptPublisher,
    TranscriptTranslator,
)
from app.domain.livekit_agents.caption_agent.transcripts.pipeline import TranscriptPipeline

__all__ = [
    "CAPTION_AGENT_NAME",
    "DEFAULT_STT_MODEL",
    "CaptionAgent",
    "CaptionAgentParams",
    "CaptionAgentService",
    "CaptionEngine",
    "CaptionEngineMode",
    "CaptionS3Uploader",
    "CompositeTranscriptHandler",
    "CustomSttConfig",
    "MultiAgentCaptionEngine",
    "MultiSpeakerCaptionManager",
    "RoomCaptionTranscriber",
    "SingleAgentCaptionEngine",
    "SpeakerSttConfig",
    "SttConfigType",
    "SttProcessor",
    "SttProvider",
    "TranscriptData",
    "TranscriptHandler",
    "TranscriptPersistenceHandler",
    "TranscriptPipeline",
    "TranscriptPublisher",
    "TranscriptTranslator",
    "build_caption_engine",
    "initialize_beanie_for_worker",
    "parse_job_metadata",
    "parse_speaker_stt_descriptor",
    "resolve_stt_model",
    "select_engine_mode",
]
