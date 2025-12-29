"""Multi-speaker caption manager for LiveKit rooms.

This module provides the MultiSpeakerCaptionManager class that manages
per-participant caption agent sessions with configurable STT models.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import TYPE_CHECKING

from livekit import rtc
from livekit.plugins import silero
from loguru import logger

from app.domain.livekit_agents.caption_agent.engines.multi_agent.caption_agent import CaptionAgent
from app.domain.livekit_agents.caption_agent.stt.config import (
    DEFAULT_STT_MODEL,
    SpeakerSttConfig,
    SttConfigType,
)

if TYPE_CHECKING:
    from livekit.agents import JobContext
    from livekit.agents.voice import AgentSession


class MultiSpeakerCaptionManager:
    """Manages per-participant caption agent sessions.

    Creates and manages separate AgentSession instances for each participant,
    allowing different STT models per speaker with automatic join/leave handling.

    Supports dynamic language updates via participant attributes:
    - Set `stt_language` attribute on a participant to change their STT language
    - The manager will restart the session with the new language configuration
    """

    # Attribute key for STT language
    STT_LANGUAGE_ATTRIBUTE = "stt_language"

    def __init__(
        self,
        ctx: JobContext,
        session_id: str,
        room_id: str,
        translation_languages: list[str] | None = None,
        speaker_configs: Mapping[str, SttConfigType] | None = None,
        default_stt: SttConfigType = DEFAULT_STT_MODEL,
    ) -> None:
        """Initialize the multi-speaker caption manager.

        Args:
            ctx: LiveKit JobContext
            session_id: Session ID for storing transcripts
            room_id: Room ID for transcript association
            translation_languages: Target languages for translation
            speaker_configs: Map of participant_identity to STT configuration
                Supports SpeakerSttConfig, CustomSttConfig, stt.STT, or str
            default_stt: Default STT model/config for speakers without specific config
        """
        from livekit.agents import utils
        from livekit.agents.voice import AgentSession, room_io

        self._AgentSession = AgentSession
        self._room_io = room_io
        self._utils = utils

        self.ctx = ctx
        self.session_id = session_id
        self.room_id = room_id
        self.translation_languages = translation_languages
        self.speaker_configs: dict[str, SttConfigType] = (
            dict(speaker_configs) if speaker_configs else {}
        )
        self.default_stt = default_stt

        self._sessions: dict[str, AgentSession] = {}
        self._participant_languages: dict[str, str] = {}  # Track current language per participant
        self._tasks: set[asyncio.Task] = set()
        self._vad = silero.VAD.load()

    def start(self) -> None:
        """Start listening for participant connections and attribute changes."""
        self.ctx.room.on("participant_connected", self._on_participant_connected)
        self.ctx.room.on("participant_disconnected", self._on_participant_disconnected)
        self.ctx.room.on("participant_attributes_changed", self._on_participant_attributes_changed)
        logger.info(
            f"MultiSpeakerCaptionManager started: session={self.session_id}, "
            f"configured_speakers={list(self.speaker_configs.keys())}"
        )

    async def aclose(self) -> None:
        """Close all sessions and cleanup."""
        await self._utils.aio.cancel_and_wait(*self._tasks)

        close_tasks = [self._close_session(s) for s in self._sessions.values()]
        if close_tasks:
            await asyncio.gather(*close_tasks, return_exceptions=True)

        self.ctx.room.off("participant_connected", self._on_participant_connected)
        self.ctx.room.off("participant_disconnected", self._on_participant_disconnected)
        self.ctx.room.off("participant_attributes_changed", self._on_participant_attributes_changed)

        logger.info(f"MultiSpeakerCaptionManager closed: session={self.session_id}")

    def handle_existing_participants(self) -> None:
        """Start sessions for all existing participants in the room.

        Also reads initial language attributes from participants.
        """
        for participant in self.ctx.room.remote_participants.values():
            # Check for existing language attribute
            if self.STT_LANGUAGE_ATTRIBUTE in participant.attributes:
                self._participant_languages[participant.identity] = participant.attributes[
                    self.STT_LANGUAGE_ATTRIBUTE
                ]
            self._on_participant_connected(participant)

    def _on_participant_connected(self, participant: rtc.RemoteParticipant) -> None:
        """Handle a new participant connection."""
        if participant.identity in self._sessions:
            logger.debug(f"Session already exists for {participant.identity}")
            return

        logger.info(f"Starting caption session for: {participant.identity}")
        task = asyncio.create_task(self._start_session(participant))
        self._tasks.add(task)

        def on_done(t: asyncio.Task) -> None:
            try:
                if not t.cancelled() and t.exception() is None:
                    self._sessions[participant.identity] = t.result()
                elif t.exception():
                    logger.error(
                        f"Failed to start session for {participant.identity}: {t.exception()}"
                    )
            finally:
                self._tasks.discard(t)

        task.add_done_callback(on_done)

    def _on_participant_disconnected(self, participant: rtc.RemoteParticipant) -> None:
        """Handle a participant disconnection."""
        session = self._sessions.pop(participant.identity, None)
        self._participant_languages.pop(participant.identity, None)
        if session is None:
            return

        logger.info(f"Closing caption session for: {participant.identity}")
        task = asyncio.create_task(self._close_session(session))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(t))

    def _on_participant_attributes_changed(
        self, changed_attributes: dict[str, str], participant: rtc.Participant
    ) -> None:
        """Handle participant attribute changes.

        When the stt_language attribute changes, restart the caption session
        for that participant with the new language configuration.
        """
        # Only process if stt_language attribute changed
        if self.STT_LANGUAGE_ATTRIBUTE not in changed_attributes:
            return

        new_language = changed_attributes[self.STT_LANGUAGE_ATTRIBUTE]
        identity = participant.identity

        # Skip if no session exists for this participant
        if identity not in self._sessions:
            logger.debug(f"No session for {identity}, storing language preference")
            self._participant_languages[identity] = new_language
            return

        # Skip if language hasn't actually changed
        current_language = self._participant_languages.get(identity)
        if current_language == new_language:
            logger.debug(f"Language unchanged for {identity}: {new_language}")
            return

        logger.info(
            f"Language change detected for {identity}: {current_language} -> {new_language}"
        )

        # Update stored language
        self._participant_languages[identity] = new_language

        # Restart session with new language
        task = asyncio.create_task(self._restart_session_with_language(identity, new_language))
        self._tasks.add(task)
        task.add_done_callback(lambda t: self._tasks.discard(t))

    async def _restart_session_with_language(self, identity: str, new_language: str) -> None:
        """Restart a participant's caption session with a new language.

        This gracefully closes the existing session and starts a new one
        with the updated STT language configuration.
        """
        logger.info(f"Restarting caption session for {identity} with language: {new_language}")

        # Close existing session
        old_session = self._sessions.pop(identity, None)
        if old_session:
            await self._close_session(old_session)

        # Find the participant
        participant = self.ctx.room.remote_participants.get(identity)
        if not participant:
            logger.warning(f"Participant {identity} not found, cannot restart session")
            return

        # Update speaker config with new language
        self.speaker_configs[identity] = SpeakerSttConfig(language=new_language)

        # Start new session
        try:
            new_session = await self._start_session(participant)
            self._sessions[identity] = new_session
            logger.info(f"Caption session restarted for {identity} with language: {new_language}")
        except Exception as exc:
            logger.exception(f"Failed to restart session for {identity}: {exc}")

    async def _start_session(self, participant: rtc.RemoteParticipant) -> AgentSession:
        """Start a caption session for a specific participant."""
        identity = participant.identity

        # Check for language from participant attributes first
        participant_language = self._participant_languages.get(identity)
        if participant_language:
            stt_config = SpeakerSttConfig(language=participant_language)
        else:
            stt_config = self.speaker_configs.get(identity, self.default_stt)

        if isinstance(stt_config, SpeakerSttConfig):
            logger.info(
                f"Using custom STT for {identity}: {stt_config.provider}/{stt_config.model}:{stt_config.language}"
            )
        else:
            logger.info(f"Using default STT for {identity}: {self.default_stt}")

        agent = CaptionAgent(
            session_id=self.session_id,
            room_id=self.room_id,
            participant_identity=identity,
            stt_config=stt_config,
            translation_languages=self.translation_languages,
            vad=self._vad,
        )
        agent.set_room(self.ctx.room)

        session = self._AgentSession()
        await session.start(
            agent=agent,
            room=self.ctx.room,
            room_options=self._room_io.RoomOptions(
                audio_input=True,
                audio_output=False,
                text_output=True,
                text_input=False,
                participant_identity=identity,
            ),
        )

        logger.info(f"Caption session started for: {identity}")
        return session

    async def _close_session(self, session: AgentSession) -> None:
        """Close a caption session gracefully."""
        try:
            await session.drain()
            await session.aclose()
        except Exception as exc:
            logger.warning(f"Error closing session: {exc}")
