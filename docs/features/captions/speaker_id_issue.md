# Speaker ID Not Set for Transcripts

## Problem

`speech_data.speaker_id` is always `None` in `CaptionAgent._process_final_transcript()`.

## Root Cause

The `speaker_id` field in `stt.SpeechData` is only populated by STT providers that support **speaker diarization**. Our current STT model (Cartesia `ink-whisper`) does not support diarization.

### STT Providers with Diarization Support

| Provider                   | Diarization | How to Enable                               |
| -------------------------- | ----------- | ------------------------------------------- |
| **Speechmatics**           | ✅          | `speechmatics.STT(enable_diarization=True)` |
| **Deepgram**               | ✅          | `deepgram.STT(enable_diarization=True)`     |
| **Cartesia (ink-whisper)** | ❌          | Not supported                               |

### Current Architecture

`MultiSpeakerCaptionManager` already routes audio per-participant:

- Each `CaptionAgent` receives audio from **one specific participant**
- `participant_identity` is set on each agent instance
- STT diarization is **redundant** in this setup since we already know who's speaking

## Schema Context

`Transcript` model has two speaker-related fields:

- `speaker_id`: STT-detected speaker from diarization (currently always `None`)
- `participant_identity`: RTC participant identity (always set correctly)

## Options

### Option A: Use `participant_identity` as `speaker_id`

Since we route audio per-participant, use `participant_identity` as the speaker identifier:

```python
speaker_id = speech_data.speaker_id or self.participant_identity
```

**Pros**: Simple, works with current architecture  
**Cons**: Redundant with `participant_identity` field

### Option B: Remove `speaker_id` field

Remove `speaker_id` from `Transcript` schema, use only `participant_identity`.

**Pros**: Cleaner schema, no redundancy  
**Cons**: Loses future diarization capability

### Option C: Switch to Diarization-Capable STT

Use Deepgram or Speechmatics with diarization enabled.

**Pros**: True speaker detection, works for single-audio-stream scenarios  
**Cons**: May be overkill for per-participant routing, different pricing/latency

### Option D: Keep as-is

Accept that `speaker_id` is `None` when using non-diarization STT.

**Pros**: No changes needed  
**Cons**: `speaker_id` field is misleading/unused

## References

- Provider diarization documentation is intentionally redacted in this public demo: `https://<redacted-stt-provider-docs>`
- [Deepgram STT Plugin](https://github.com/livekit/agents/blob/main/livekit-plugins/livekit-plugins-deepgram/livekit/plugins/deepgram/stt.py) - `enable_diarization` parameter
- [SpeechData class](https://github.com/livekit/agents/blob/main/livekit-agents/livekit/agents/stt/stt.py) - `speaker_id: str | None = None`
