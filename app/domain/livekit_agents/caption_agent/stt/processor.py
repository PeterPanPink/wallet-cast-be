"""STT processor for handling speech-to-text streaming.

This module provides the SttProcessor class that handles STT processing,
supporting both built-in Agent STT and custom standalone STT implementations.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterable, Awaitable, Callable
from typing import TYPE_CHECKING

from livekit import rtc
from livekit.agents import Agent, ModelSettings, stt, utils, vad
from livekit.plugins import silero

from app.domain.livekit_agents.caption_agent.stt.config import CustomSttConfig

if TYPE_CHECKING:
    pass


# Type alias for speech event callback
SpeechEventCallback = Callable[[stt.SpeechEvent], Awaitable[None]]


class SttProcessor:
    """Handles STT streaming for both built-in and custom configurations.

    This class encapsulates all STT processing logic, supporting:
    - Built-in Agent STT with default.stt_node()
    - Custom standalone STT with push_frame/async iteration pattern
    - Optional VAD wrapping for non-streaming STT implementations
    """

    def __init__(
        self,
        custom_stt_config: CustomSttConfig | None = None,
        vad_instance: vad.VAD | None = None,
    ) -> None:
        """Initialize the STT processor.

        Args:
            custom_stt_config: Configuration for custom STT (if not using built-in)
            vad_instance: Pre-loaded VAD instance for StreamAdapter wrapping
        """
        self._custom_stt_config = custom_stt_config
        self._vad_instance = vad_instance or silero.VAD.load()
        self._use_custom_stt = custom_stt_config is not None
        self._event_callback: SpeechEventCallback | None = None

    def set_event_callback(self, callback: SpeechEventCallback) -> None:
        """Set the callback for speech events.

        Args:
            callback: Async function to call for each speech event
        """
        self._event_callback = callback

    @property
    def uses_custom_stt(self) -> bool:
        """Whether this processor uses custom STT mode."""
        return self._use_custom_stt

    async def process_stream(
        self,
        agent: Agent,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> AsyncIterable[stt.SpeechEvent]:
        """Process audio stream and yield speech events.

        Routes to appropriate processing method based on configuration.

        Args:
            agent: The parent Agent instance (for built-in STT)
            audio: Async iterable of audio frames
            model_settings: Model settings for built-in STT

        Yields:
            Speech events from STT processing
        """
        if self._use_custom_stt and self._custom_stt_config is not None:
            async for event in self._process_custom_stream(audio):
                yield event
        else:
            async for event in self._process_builtin_stream(agent, audio, model_settings):
                yield event

    async def _process_builtin_stream(
        self,
        agent: Agent,
        audio: AsyncIterable[rtc.AudioFrame],
        model_settings: ModelSettings,
    ) -> AsyncIterable[stt.SpeechEvent]:
        """Process STT using built-in Agent.default.stt_node().

        Args:
            agent: The parent Agent instance
            audio: Async iterable of audio frames
            model_settings: Model settings for STT

        Yields:
            Speech events from the built-in STT processor
        """
        events = Agent.default.stt_node(agent, audio, model_settings)
        if events is None:
            return

        async for event in events:
            if isinstance(event, stt.SpeechEvent) and self._event_callback:
                await self._event_callback(event)
            yield event

    async def _process_custom_stream(
        self,
        audio: AsyncIterable[rtc.AudioFrame],
    ) -> AsyncIterable[stt.SpeechEvent]:
        """Process STT using custom standalone streaming pattern.

        This implements the custom STT pattern from LiveKit docs:
        - Creates an STT stream
        - Pushes audio frames to the stream
        - Processes speech events from the stream
        - Optionally wraps with StreamAdapter for non-streaming STT + VAD

        Args:
            audio: Async iterable of audio frames

        Yields:
            Speech events from custom STT processing
        """
        if self._custom_stt_config is None:
            return

        custom_stt = self._custom_stt_config.stt

        # Wrap with StreamAdapter if using VAD (for non-streaming STT like Whisper)
        if self._custom_stt_config.use_vad:
            wrapped_stt = stt.StreamAdapter(stt=custom_stt, vad=self._vad_instance)
        else:
            wrapped_stt = custom_stt

        stt_stream = wrapped_stt.stream()

        async def _forward_audio() -> None:
            """Forward audio frames to the STT stream."""
            try:
                async for frame in audio:
                    stt_stream.push_frame(frame)
            finally:
                with contextlib.suppress(RuntimeError):
                    stt_stream.end_input()

        # Start forwarding audio in background
        forward_task = asyncio.create_task(_forward_audio())

        try:
            # Process speech events from the stream
            async for event in stt_stream:
                if self._event_callback:
                    await self._event_callback(event)
                yield event
        finally:
            await utils.aio.cancel_and_wait(forward_task)
            await stt_stream.aclose()
