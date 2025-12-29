# Caption Upload to Object Storage (Sanitized Demo)

## Overview

Automated system to upload caption files (.m3u8 playlists and .vtt segments) to an object storage service for live sessions.

## Architecture

### Components

1. **Session Schema** (`app/schemas/session.py`)

   - Added `caption_last_uploaded_segment: int | None` - tracks last uploaded segment number
   - Added `caption_s3_urls: dict[str, str] | None` - maps file keys to object storage URLs

2. **Object Storage Service** (`app/services/cw_s3.py`)

   - Added `upload_caption_files_batch()` - efficiently uploads multiple files concurrently
   - Returns dict mapping filenames to public object storage URLs

3. **Caption Agent Worker** (`app/workers/caption_agent_worker.py`)
   - Background task `upload_captions_to_s3_task()` runs every 5 seconds
   - Queries active caption agent sessions from Redis
   - Uploads new segments incrementally based on `caption_last_uploaded_segment`

### Upload Flow

```
┌─────────────────────────────────────────────────────────────┐
│           Periodic Object Storage Upload Task                 │
│                   (every 5 seconds)                          │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       ▼
         ┌─────────────────────────────┐
         │ Query Redis for active      │
         │ caption agent sessions      │
         └──────────┬──────────────────┘
                    │
                    ▼
         ┌─────────────────────────────┐
         │ For each session:           │
         │ - Get transcripts from DB   │
         │ - Calculate latest segment  │
         │ - Identify new segments     │
         └──────────┬──────────────────┘
                    │
                    ▼
         ┌─────────────────────────────┐
         │ Generate files:             │
         │ - VTT segments (orig + i18n)│
         │ - M3U8 playlists (per lang) │
         └──────────┬──────────────────┘
                    │
                    ▼
         ┌─────────────────────────────┐
         │ Batch upload to storage     │
         │ (concurrent uploads)        │
         └──────────┬──────────────────┘
                    │
                    ▼
         ┌─────────────────────────────┐
         │ Update Session:             │
         │ - last_uploaded_segment     │
         │ - caption_s3_urls           │
         └─────────────────────────────┘
```

## File Structure in Object Storage

```
storage://bucket-name/captions/{session_id}/
├── captions.m3u8                  # Original language playlist
├── captions-es.m3u8               # Spanish translation playlist
├── captions-fr.m3u8               # French translation playlist
├── captions-ja.m3u8               # Japanese translation playlist
├── captions-0.vtt                 # Segment 0 (original)
├── captions-es-0.vtt              # Segment 0 (Spanish)
├── captions-fr-0.vtt              # Segment 0 (French)
├── captions-ja-0.vtt              # Segment 0 (Japanese)
├── captions-1.vtt                 # Segment 1 (original)
├── captions-es-1.vtt              # Segment 1 (Spanish)
└── ...
```

## M3U8 Playlist Format

Each playlist references absolute object storage URLs:

```m3u8
#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:4
#EXT-X-MEDIA-SEQUENCE:0

#EXTINF:4.0,
https://<redacted-storage-host>/captions/session-123/captions-0.vtt
#EXTINF:4.0,
https://<redacted-storage-host>/captions/session-123/captions-1.vtt
...
```

## Configuration

- **STORAGE_UPLOAD_INTERVAL**: 5.0 seconds (configurable in worker)
- **STORAGE_ENABLED**: `True` by default (feature flag)
- **Segment Duration**: 4 seconds (inherited from `SEGMENT_DURATION`)
- **Max Segments**: 100 (only last 100 segments kept in playlist)

## Performance Optimizations

1. **Incremental Uploads**: Only uploads new segments since `caption_last_uploaded_segment`
2. **Batch Uploads**: Uses `upload_caption_files_batch()` to upload multiple files concurrently
3. **Lightweight Task**: Runs in caption agent worker, no separate worker needed
4. **Redis Query**: Only processes sessions marked as "running" in Redis

## Error Handling

- Individual session failures are logged but don't stop other sessions
- Task-level errors trigger 5-second backoff before retry
- Type-safe with proper error boundaries

## Usage

### Enable/Disable Feature

Set `STORAGE_ENABLED = False` in `caption_agent_worker.py` to disable uploads.

### Check Upload Status

```python
session = await Session.find_one(Session.session_id == session_id)
print(f"Last uploaded segment: {session.caption_last_uploaded_segment}")
print(f"Storage URLs: {session.caption_s3_urls}")
```

### Access Caption Files

Original language:

```
https://<redacted-storage-host>/captions/{session_id}/captions.m3u8
```

Translated (Spanish):

```
https://<redacted-storage-host>/captions/{session_id}/captions-es.m3u8
```

## Testing

All tests pass with the new fields:

```bash
make test-fast
# 321 passed, 9 skipped, 2 deselected, 1 warning
```

## Future Enhancements

1. **Cleanup Task**: Delete old segments beyond retention period
2. **CDN Integration**: Add CloudFront distribution support
3. **Compression**: Gzip compress VTT/M3U8 files
4. **Metrics**: Track upload success rate, latency, file sizes
5. **Adaptive Upload**: Adjust interval based on session activity
