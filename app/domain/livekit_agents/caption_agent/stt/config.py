"""STT configuration models for caption engines.

This module provides configuration classes for Speech-to-Text processing
in the caption agent system.

Classes:
    - SttProvider: Enum of supported STT providers
    - SpeakerSttConfig: Configuration for built-in OpenAI STT
    - CustomSttConfig: Configuration for custom STT implementations
"""

from __future__ import annotations

from enum import Enum

from livekit.agents import stt
from pydantic import BaseModel


class SttProvider(str, Enum):
    """Supported STT providers.

    Note: Currently only OpenAI with gpt-realtime transcription is supported.
    """

    OPENAI = "openai"


class SpeakerSttConfig(BaseModel):
    """Configuration for a speaker's STT model.

    Uses OpenAI's gpt-realtime transcription API for high-quality,
    low-latency speech-to-text with streaming support.

    Attributes:
        provider: The STT provider (currently only OpenAI)
        model: The OpenAI model name (gpt-4o-transcribe or gpt-4o-mini-transcribe)
        language: Language code for transcription (ISO 639-1, e.g., 'en', 'es', 'ja')
    """

    provider: SttProvider = SttProvider.OPENAI
    model: str = "gpt-4o-transcribe"
    language: str = "en"

    def to_stt_descriptor(self) -> str:
        """Convert to LiveKit Inference STT descriptor string."""
        return f"{self.provider.value}/{self.model}:{self.language}"

    def to_stt_instance(self) -> stt.STT:
        """Create an OpenAI STT plugin instance with realtime transcription.

        Uses OpenAI's gpt-realtime API for streaming transcription with
        server-side VAD (Voice Activity Detection).
        """
        from livekit.plugins import openai as openai_stt

        return openai_stt.STT(
            model=self.model,
            language=self.language,
            use_realtime=True,
        )


class CustomSttConfig(BaseModel):
    """Configuration for using a custom STT implementation.

    Use this when you want to bypass the built-in Agent STT pipeline and
    implement your own standalone STT processing using the streaming interface.

    The custom STT instance should support streaming via `stt.stream()`,
    with `push_frame()` for audio input and async iteration for speech events.

    Example:
        ```python
        from livekit.plugins import deepgram

        custom_config = CustomSttConfig(
            stt=deepgram.STT(model="nova-2"),
            use_vad=True,  # Wrap with VAD for non-streaming STT
        )
        ```

    Attributes:
        stt: The STT instance to use for transcription
        use_vad: Whether to wrap the STT with VAD (for non-streaming STT like Whisper)
    """

    model_config = {"arbitrary_types_allowed": True}

    stt: stt.STT
    use_vad: bool = False


# Union type for STT configuration
SttConfigType = SpeakerSttConfig | CustomSttConfig | stt.STT | str

# Default STT uses OpenAI Whisper via the LiveKit plugin
DEFAULT_STT_MODEL = SpeakerSttConfig()


def parse_speaker_stt_descriptor(descriptor: str) -> SpeakerSttConfig | None:
    """Parse a descriptor string into a SpeakerSttConfig when applicable.

    LiveKit "provider/model:language" strings are used by LiveKit Inference, but for some
    providers (notably OpenAI) our app uses the plugin instead. This helper converts
    OpenAI descriptors (e.g. "openai/gpt-4o-transcribe:en") into SpeakerSttConfig.
    """
    # Only handle OpenAI-style descriptors; everything else should remain a string so
    # it can be handled by LiveKit Inference or other mechanisms.
    if not descriptor.startswith("openai/"):
        return None

    rest = descriptor.removeprefix("openai/")
    model, sep, language = rest.partition(":")
    model = model.strip()
    language = (language.strip() if sep else "en") or "en"
    if not model:
        return None

    return SpeakerSttConfig(provider=SttProvider.OPENAI, model=model, language=language)


def resolve_stt_model(
    stt_config: SttConfigType,
) -> tuple[stt.STT | str | None, CustomSttConfig | None]:
    """Resolve STT configuration to an STT model and optional custom config.

    Args:
        stt_config: The STT configuration to resolve

    Returns:
        A tuple of (stt_model, custom_config):
        - stt_model: The STT model to pass to Agent, or None for custom STT
        - custom_config: The CustomSttConfig if using custom STT, else None
    """
    if isinstance(stt_config, CustomSttConfig):
        return None, stt_config
    elif isinstance(stt_config, SpeakerSttConfig):
        return stt_config.to_stt_instance(), None
    elif isinstance(stt_config, stt.STT):
        return stt_config, None
    else:
        return stt_config, None  # str descriptor
