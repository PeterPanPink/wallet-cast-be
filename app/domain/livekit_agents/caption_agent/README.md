# Caption Agent

Real-time transcription (+ optional translation) for LiveKit rooms; transcripts are:
- persisted to MongoDB,
- optionally translated,
- published to the room data channel for live captions,
- optionally uploaded to S3 as segmented WebVTT for HLS.

## Where It Runs

- Worker (starts the LiveKit `AgentServer` and handles ARQ tasks): `app/workers/caption_agent_worker.py`
- Agent dispatch + entrypoint: `service.py`
- Engine selection (single vs multi agent): `orchestrator.py`
- Engine implementations:
  - Single-agent (one job transcribes all participants): `engines/single_agent/`
  - Multi-agent (one AgentSession per participant): `engines/multi_agent/`

## STT Configuration (Important)

This project supports three STT modes:

1) **OpenAI via plugin (default)**  
Use `SpeakerSttConfig` (provider/model/language). This creates a plugin STT instance (no LiveKit Inference).

2) **LiveKit Inference via descriptor string**  
Use an inference descriptor string like `deepgram/nova-3:multi`.  
Note: LiveKit Inference does **not** support `openai/...` descriptors (you’ll see `provider not supported`).

3) **Custom STT implementation**  
Use `CustomSttConfig(stt=..., use_vad=...)` and implement streaming via `stt.stream()` (or wrap with VAD using `StreamAdapter`).

`default_stt` metadata handling:
- `dict` → treated as `SpeakerSttConfig` (plugin mode)
- `str` → treated as inference descriptor, except legacy `openai/...` strings which are parsed into `SpeakerSttConfig`

## Participant Language Updates

If a participant sets the `stt_language` attribute, engines may restart that participant’s STT stream/session with the new `SpeakerSttConfig(language=...)`.

## Documentation

More detailed docs live in `docs/`:

- **General Agents Documentation**: [AGENTS.md](../../../../docs/AGENTS.md)
- **Captions Feature Documentation**: [docs/features/captions](../../../../docs/features/captions/README.md)
  - [Frontend Integration](../../../../docs/features/captions/frontend_integration.md)
  - [Participant Language Update](../../../../docs/features/captions/participant_language_update.md)
  - [Speaker ID Issues](../../../../docs/features/captions/speaker_id_issue.md)
- **S3 Upload**: [docs/features/caption_s3_upload.md](../../../../docs/features/caption_s3_upload.md)

## Key Files

- `service.py`: Service layer + LiveKit job entrypoint registration.
- `orchestrator.py`: Mode selection and engine wiring.
- `stt/`: STT configuration and helpers.
- `transcripts/`: Transcript handlers and pipeline.
- `delivery/`: S3 uploader.
