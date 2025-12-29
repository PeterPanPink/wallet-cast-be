# Caption Feature

Real-time speech-to-text transcription with translation for live sessions.

## Architecture

```
RTC Provider Room → CaptionAgent (STT) → Document DB (Transcript) → Object Storage (WebVTT segments)
                      ↓
               Room Data Channel (live captions)
```

## Key Components

| Component                    | Location                                           | Purpose                               |
| ---------------------------- | -------------------------------------------------- | ------------------------------------- |
| `CaptionAgent`               | `app/domain/livekit_agents/caption_agent.py`       | STT processing, publishes transcripts |
| `MultiSpeakerCaptionManager` | Same file                                          | Per-participant audio routing         |
| `CaptionStorageUploader`     | `app/domain/livekit_agents/caption_s3_uploader.py` | Periodic WebVTT upload to storage     |
| `Transcript`                 | `app/schemas/transcript.py`                        | Document DB model                     |

## Data Flow

1. **Live**: Audio → STT → Transcript (Document DB) + Room Data Channel
2. **Egress**: Transcript query → WebVTT generation → storage upload → CDN delivery

## Multi-Speaker Mode

Each participant gets a dedicated `CaptionAgent` via `MultiSpeakerCaptionManager`:

- Audio routed per-participant using `RoomOptions(participant_identity=...)`
- Supports per-speaker STT model configuration

## Caption Delivery

| Use Case     | Method                                         |
| ------------ | ---------------------------------------------- |
| Live viewing | Room data channel (`topic: "live-transcript"`) |
| VOD/Playback | CDN + Object Storage (WebVTT segments)         |
| Dev/Demo     | API endpoints (not for production)             |

## Known Issues

- [speaker_id_issue.md](speaker_id_issue.md) - STT speaker_id not set
- [modes.md](modes.md) - Single vs Multi-Speaker mode comparison
