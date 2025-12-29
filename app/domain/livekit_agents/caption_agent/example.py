"""Caption Agent Usage Examples.

This module demonstrates how to use the caption agent system for
real-time multi-speaker transcription with LiveKit.

Run with: python -m app.domain.livekit_agents.example
"""

# =============================================================================
# Example 1: Basic Usage - Start caption agent via service dispatch
# =============================================================================


async def example_dispatch_caption_agent() -> None:
    """Dispatch a caption agent to a LiveKit room via the service layer.

    This is the typical production usage pattern where the CaptionAgentService
    handles agent lifecycle and dispatches agents via LiveKit's agent dispatch.
    """
    from app.domain.livekit_agents.caption_agent import CaptionAgentParams, CaptionAgentService

    # Create the service
    service = CaptionAgentService(redis_label="flc_primary")

    # Define parameters for the caption agent
    params = CaptionAgentParams(
        session_id="session-123",
        translation_languages=["Spanish", "French", "Japanese"],
    )

    # Dispatch the agent to the room
    result = await service.start_caption_agent(params)
    print(f"Agent started: {result}")

    # Later, stop the agent
    await service.stop_caption_agent(session_id="session-123")


# =============================================================================
# Example 2: Per-Speaker STT Configuration
# =============================================================================


async def example_per_speaker_stt() -> None:
    """Configure different STT models for different speakers.

    Useful when speakers have different languages or you want to use
    specific models optimized for certain speakers.
    """
    from app.domain.livekit_agents.caption_agent import (
        CaptionAgentParams,
        CaptionAgentService,
        SpeakerSttConfig,
        SttProvider,
    )

    service = CaptionAgentService(redis_label="flc_primary")

    # Configure per-speaker STT models
    speaker_configs = {
        # Host speaks English - use OpenAI gpt-4o-transcribe
        "host-user-id": SpeakerSttConfig(
            provider=SttProvider.OPENAI,
            model="gpt-4o-transcribe",
            language="en",
        ),
        # Guest speaks Spanish - use OpenAI gpt-4o-transcribe with Spanish
        "guest-user-id": SpeakerSttConfig(
            provider=SttProvider.OPENAI,
            model="gpt-4o-transcribe",
            language="es",
        ),
    }

    params = CaptionAgentParams(
        session_id="session-456",
        speaker_configs=speaker_configs,
    )

    result = await service.start_caption_agent(params)
    print(f"Agent started with per-speaker config: {result}")


# =============================================================================
# Example 3: Direct Agent Usage (for testing/development)
# =============================================================================


async def example_direct_manager_usage() -> None:
    """Use MultiSpeakerCaptionManager directly in a LiveKit agent entrypoint.

    This shows how the manager works internally - typically you'd use
    CaptionAgentService instead, but this is useful for understanding
    the architecture or custom implementations.
    """
    from livekit.agents import AutoSubscribe, JobContext

    from app.domain.livekit_agents.caption_agent import (
        MultiSpeakerCaptionManager,
        SpeakerSttConfig,
        SttProvider,
    )

    async def my_agent_entrypoint(ctx: JobContext) -> None:
        """Custom agent entrypoint."""
        # Connect to the room
        await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

        # Create the manager
        manager = MultiSpeakerCaptionManager(
            ctx=ctx,
            session_id="my-session",
            room_id=ctx.room.name,
            translation_languages=["Spanish", "French"],
            speaker_configs={
                "speaker-1": SpeakerSttConfig(
                    provider=SttProvider.OPENAI,
                    model="gpt-4o-transcribe",
                    language="en",
                ),
            },
        )

        # Start listening for participants
        manager.start()

        # Handle any participants already in the room
        manager.handle_existing_participants()

        # Register cleanup on shutdown
        ctx.add_shutdown_callback(manager.aclose)

    # NOTE: This is just a demonstration - you'd register this with AgentServer:
    # agent_server.rtc_session(agent_name="my-agent")(my_agent_entrypoint)


# =============================================================================
# Example 4: Running the Agent Server (Worker Process)
# =============================================================================


async def example_run_agent_server() -> None:
    """Start the agent server as a background task.

    This is typically done in a worker process, not the main API server.
    """
    from app.domain.livekit_agents.caption_agent import CaptionAgentService

    service = CaptionAgentService(redis_label="flc_primary")

    # Start the agent server (runs in background)
    await service.start_agent_server()

    # Optionally start S3 uploader for HLS caption delivery
    service.start_s3_uploader()

    # ... application runs ...

    # Cleanup on shutdown
    await service.stop_s3_uploader()
    await service.stop_agent_server()


# =============================================================================
# Example 5: Data Flow Overview
# =============================================================================
"""
Data Flow:
                                 ┌──────────────────┐
                                 │   LiveKit Room   │
                                 └────────┬─────────┘
                                          │ Audio streams
                                          ▼
                          ┌───────────────────────────────┐
                          │ MultiSpeakerCaptionManager    │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │ CaptionAgent (Speaker A)│  │
                          │  │ - STT: OpenAI/Chinese   │  │
                          │  └─────────────────────────┘  │
                          │                               │
                          │  ┌─────────────────────────┐  │
                          │  │ CaptionAgent (Speaker B)│  │
                          │  │ - STT: OpenAI/English   │  │
                          │  └─────────────────────────┘  │
                          └───────────────┬───────────────┘
                                          │
                     ┌────────────────────┼────────────────────┐
                     │                    │                    │
                     ▼                    ▼                    ▼
           ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
           │ MongoDB         │  │ Room Data       │  │ S3 (via         │
           │ (Transcript)    │  │ Channel         │  │ CaptionS3       │
           │                 │  │ (live captions) │  │ Uploader)       │
           └─────────────────┘  └─────────────────┘  └─────────────────┘

Key Components:
- CaptionAgent: Handles STT for one participant, saves to MongoDB, publishes to room
- MultiSpeakerCaptionManager: Creates CaptionAgent per participant, manages lifecycle
- CaptionAgentService: Dispatches agents via LiveKit, manages server lifecycle
- CaptionS3Uploader: Periodically uploads WebVTT segments to S3 for VOD
"""


if __name__ == "__main__":
    # Run a simple example
    print("Caption Agent Examples")
    print("=" * 50)
    print()
    print("See the source code for usage examples.")
    print()
    print("Key classes:")
    print("  - MultiSpeakerCaptionManager: Per-participant STT management")
    print("  - CaptionAgent: Single-participant STT processing")
    print("  - SpeakerSttConfig: STT model configuration")
    print("  - CaptionAgentService: Agent lifecycle management")
    print()

    # Example: just show the params model
    from app.domain.livekit_agents.caption_agent import (
        CaptionAgentParams,
        SpeakerSttConfig,
        SttProvider,
    )

    params = CaptionAgentParams(
        session_id="demo-session",
        translation_languages=["Spanish", "French"],
        speaker_configs={
            "host": SpeakerSttConfig(
                provider=SttProvider.OPENAI,
                model="gpt-4o-transcribe",
                language="zh",
            ),
        },
    )
    print("Example CaptionAgentParams:")
    print(params.model_dump_json(indent=2))
