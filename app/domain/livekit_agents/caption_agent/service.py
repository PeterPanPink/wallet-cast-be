"""Caption agent service for managing agent lifecycle.

This module provides:
- Agent entrypoint function for LiveKit agent dispatch
- CaptionAgentService for starting/stopping caption agents
- S3 uploader management for HLS caption delivery
"""

import asyncio
import contextlib
import json
from typing import Any

from livekit.agents import AgentServer, AutoSubscribe, JobContext
from loguru import logger
from pydantic import BaseModel, Field

from app.shared.storage.mongo import get_mongo_client
from app.shared.storage.redis import get_redis_client
from app.domain.livekit_agents.caption_agent.delivery.s3_uploader import CaptionS3Uploader
from app.domain.livekit_agents.caption_agent.orchestrator import (
    build_caption_engine,
    parse_job_metadata,
)
from app.domain.livekit_agents.caption_agent.stt.config import SpeakerSttConfig
from app.schemas import Session
from app.schemas.init import init_beanie_odm
from app.services.integrations.livekit_service import livekit_service

CAPTION_AGENT_NAME = "caption-agent"
FLC_MONGO_LABEL = "flc_primary"

_agent_server = AgentServer()


async def caption_agent_entrypoint(ctx: JobContext) -> None:
    """LiveKit agent entrypoint function.

    Selects a caption engine implementation and wires it to the room lifecycle.
    """
    metadata = parse_job_metadata(ctx.job.metadata)
    logger.info(f"Caption agent starting: {metadata}")

    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    engine = build_caption_engine(ctx, metadata)
    engine.start()
    engine.handle_existing()

    ctx.add_shutdown_callback(engine.aclose)
    logger.info(f"Caption engine started for room={ctx.room.name}")


_agent_server.rtc_session(agent_name=CAPTION_AGENT_NAME)(caption_agent_entrypoint)


class CaptionAgentParams(BaseModel):
    """Parameters for starting a caption agent.

    Attributes:
        session_id: The session ID for transcript storage
        translation_languages: Target languages for translation
        speaker_configs: Map of participant_identity to STT configuration
        default_stt: Default STT model for speakers without specific config
    """

    session_id: str
    translation_languages: list[str] | None = None
    speaker_configs: dict[str, SpeakerSttConfig] | None = None
    default_stt: SpeakerSttConfig | str = Field(default_factory=SpeakerSttConfig)


class CaptionAgentService:
    """Service for managing caption agent lifecycle."""

    def __init__(self, redis_label: str) -> None:
        """Initialize the caption agent service.

        Args:
            redis_label: Redis connection label
        """
        self._redis_label = redis_label
        self._agent_server = _agent_server
        self._agent_server_task: asyncio.Task | None = None
        self._s3_uploader: CaptionS3Uploader | None = None
        self._s3_upload_task: asyncio.Task | None = None

    @property
    def agent_server(self) -> AgentServer:
        """Get the agent server instance."""
        return self._agent_server

    async def start_agent_server(self) -> None:
        """Start the LiveKit agent server in the background."""
        logger.info("Starting LiveKit agent server...")
        self._agent_server_task = asyncio.create_task(
            self._agent_server.run(devmode=False, unregistered=False)
        )
        logger.info("LiveKit agent server started")

    async def stop_agent_server(self) -> None:
        """Stop the LiveKit agent server gracefully."""
        logger.info("Stopping LiveKit agent server...")
        if self._agent_server_task and not self._agent_server_task.done():
            await self._agent_server.aclose()
            try:
                await asyncio.wait_for(self._agent_server_task, timeout=30.0)
            except TimeoutError:
                logger.warning("Agent server shutdown timed out")
                self._agent_server_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._agent_server_task
        logger.info("LiveKit agent server stopped")

    def start_s3_uploader(self) -> None:
        """Start the S3 caption uploader background task."""
        logger.info("Starting S3 caption uploader...")
        self._s3_uploader = CaptionS3Uploader(redis_label=self._redis_label)
        self._s3_upload_task = asyncio.create_task(self._s3_uploader.run())

    async def stop_s3_uploader(self) -> None:
        """Stop the S3 caption uploader background task."""
        if self._s3_upload_task and not self._s3_upload_task.done():
            logger.info("Stopping S3 caption uploader...")
            if self._s3_uploader:
                self._s3_uploader.stop()
            self._s3_upload_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._s3_upload_task

    async def start_caption_agent(self, params: CaptionAgentParams) -> dict[str, Any]:
        """Start a caption agent for a session.

        Args:
            params: Caption agent parameters

        Returns:
            dict with status and agent info
        """
        logger.info(f"Starting caption agent: session={params.session_id}")

        try:
            redis = get_redis_client(self._redis_label)

            session = await Session.find_one(Session.session_id == params.session_id)
            if not session:
                logger.error(f"Session not found: {params.session_id}")
                return {
                    "status": "error",
                    "error": f"Session not found: {params.session_id}",
                    "session_id": params.session_id,
                }

            room_name = session.room_id
            agent_key = f"caption-agent:{params.session_id}"

            await redis.hset(
                agent_key,
                mapping={  # type: ignore[misc]
                    "session_id": params.session_id,
                    "room_name": room_name,
                    "status": "starting",
                },
            )
            await redis.expire(agent_key, 86400)  # type: ignore[misc]

            # Serialize speaker configs for metadata
            speaker_configs_serialized: dict[str, dict] = {}
            if params.speaker_configs:
                for identity, config in params.speaker_configs.items():
                    speaker_configs_serialized[identity] = config.model_dump()

            agent_metadata = {
                "session_id": params.session_id,
                "translation_languages": params.translation_languages,
                "speaker_configs": speaker_configs_serialized,
                "default_stt": (
                    params.default_stt.model_dump()
                    if isinstance(params.default_stt, SpeakerSttConfig)
                    else params.default_stt
                ),
            }

            dispatch = await livekit_service.create_agent_dispatch(
                agent_name=CAPTION_AGENT_NAME,
                room_name=room_name,
                metadata=json.dumps(agent_metadata),
            )

            await redis.hset(agent_key, "status", "running")  # type: ignore[misc]

            logger.info(f"Caption agent dispatched: session={params.session_id}")

            return {
                "status": "success",
                "session_id": params.session_id,
                "room_name": room_name,
                "agent_key": agent_key,
                "dispatch_id": getattr(dispatch, "id", None),
            }

        except Exception as exc:
            logger.exception(f"Failed to start caption agent: {exc}")
            return {
                "status": "error",
                "error": str(exc),
                "session_id": params.session_id,
            }

    async def stop_caption_agent(self, session_id: str) -> dict[str, Any]:
        """Stop a caption agent for a session.

        Args:
            session_id: Session ID to stop agent for

        Returns:
            dict with status
        """
        logger.info(f"Stopping caption agent: session={session_id}")

        try:
            redis = get_redis_client(self._redis_label)
            agent_key = f"caption-agent:{session_id}"
            await redis.hset(agent_key, "status", "stopped")  # type: ignore[misc]

            return {"status": "success", "session_id": session_id}

        except Exception as exc:
            logger.exception(f"Failed to stop caption agent: {exc}")
            return {"status": "error", "error": str(exc), "session_id": session_id}


async def initialize_beanie_for_worker() -> None:
    """Initialize Beanie ODM for the worker process."""
    logger.info("Initializing Beanie ODM...")
    mongo_client = get_mongo_client(FLC_MONGO_LABEL)
    database = mongo_client.get_database()
    await init_beanie_odm(database)
    logger.info("Beanie ODM initialized")
