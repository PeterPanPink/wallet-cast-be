# Caption Frontend Integration Guide

## Overview

Real-time captions with multi-language translation support. Captions are delivered via:

1. **Live**: RTC Provider Data Channel (real-time)
2. **VOD/Playback**: WebVTT segments via Object Storage/CDN or API

---

## 1. Live Captions (Data Channel)

### Subscribe to Live Transcripts

Listen to the RTC room data channel for real-time captions:

```typescript
room.on(RoomEvent.DataReceived, (payload, participant, kind, topic) => {
  if (topic === "live-transcript") {
    const caption = JSON.parse(new TextDecoder().decode(payload));
    // Handle caption
  }
});
```

### Live Caption Payload Schema

```typescript
interface LiveCaption {
  text: string; // Transcribed text
  language: string | null; // Source language code (e.g., "zh", "en")
  translations: Record<string, string> | null; // { "es": "Hola", "fr": "Bonjour" }
  speaker_id: string | null; // STT-detected speaker (often null)
  participant_identity: string; // RTC participant identity
}
```

**Example payload:**

```json
{
  "text": "你好，欢迎大家",
  "language": "zh",
  "translations": {
    "es": "Hola, bienvenidos a todos",
    "fr": "Bonjour, bienvenue à tous",
    "ja": "こんにちは、皆さんようこそ",
    "ko": "안녕하세요, 여러분 환영합니다"
  },
  "speaker_id": null,
  "participant_identity": "user_123"
}
```

---

## 2. Caption Control APIs

### Base URL: `/session/ingress/caption`

### Enable Captions

```http
POST /session/ingress/caption/enable
```

**Request:**

```json
{
  "session_id": "sess_abc123", // OR room_id (one required)
  "translation_languages": ["es", "fr", "ja", "ko"] // Optional, defaults shown
}
```

**Response:**

```json
{
  "results": {
    "session_id": "sess_abc123",
    "status": "starting",
    "job_id": "arq:job:123"
  }
}
```

### Disable Captions

```http
POST /session/ingress/caption/disable
```

**Request:**

```json
{
  "session_id": "sess_abc123" // OR room_id
}
```

**Response:**

```json
{
  "results": {
    "session_id": "sess_abc123",
    "status": "stopping",
    "job_id": "arq:job:456"
  }
}
```

### Get Caption Status

```http
POST /session/ingress/caption/status
```

**Request:**

```json
{
  "session_id": "sess_abc123" // OR room_id
}
```

**Response:**

```json
{
  "results": {
    "session_id": "sess_abc123",
    "enabled": true,
    "status": "running" // "starting" | "running" | "stopped" | "not_running"
  }
}
```

### Update Participant Language

Change a participant's STT language mid-session:

```http
POST /session/ingress/caption/update-language
```

**Request:**

```json
{
  "session_id": "sess_abc123", // OR room_id
  "participant_identity": "user_456",
  "language": "es" // ISO 639-1 code
}
```

**Response:**

```json
{
  "results": {
    "session_id": "sess_abc123",
    "participant_identity": "user_456",
    "language": "es",
    "status": "updated"
  }
}
```

---

## 3. Transcript Retrieval APIs

### Base URL: `/session/egress/caption`

### Get Transcripts (JSON)

```http
GET /session/egress/caption/{session_id}/transcripts
    ?language={lang}      // Optional: filter by language
    &start_time={float}   // Optional: filter by start time (seconds)
    &end_time={float}     // Optional: filter by end time (seconds)
```

**Response:**

```json
{
  "results": {
    "session_id": "sess_abc123",
    "transcripts": [
      {
        "text": "Hello everyone",
        "language": "en",
        "confidence": 0.95,
        "start_time": 1702500000.123, // Unix timestamp (UTC)
        "end_time": 1702500002.456,
        "duration": 2.333,
        "speaker_id": null,
        "participant_identity": "user_123",
        "translations": {
          "es": "Hola a todos",
          "fr": "Bonjour à tous"
        },
        "created_at": "2024-12-14T10:00:00.123Z"
      }
    ],
    "total_count": 1,
    "language_filter": null
  }
}
```

### Get Captions (WebVTT)

Full VTT file for the session:

```http
GET /session/egress/caption/{session_id}/captions.vtt
    ?language={lang}      // Optional: get translated text instead
```

**Response:** `text/vtt`

```
WEBVTT

00:00:00.000 --> 00:00:02.333
Hello everyone

00:00:05.000 --> 00:00:07.500
Welcome to the session
```

### Get HLS Subtitle Playlist

Segmented m3u8 for live subtitle tracks:

```http
GET /session/egress/caption/{session_id}/captions.m3u8
    ?language={lang}      // Optional
```

### Get Caption Segment

Individual 4-second VTT segment:

```http
GET /session/egress/caption/{session_id}/captions-{segment_num}.vtt
    ?language={lang}      // Optional
```

### Get Master Playlist (Video + Subtitles)

HLS master playlist combining streaming provider video with subtitle tracks:

```http
GET /session/egress/caption/{session_id}/master.m3u8
```

---

## 4. Data Schemas Summary

### TranscriptItem (API Response)

| Field                  | Type                             | Description                   |
| ---------------------- | -------------------------------- | ----------------------------- |
| `text`                 | `string`                         | Transcribed text              |
| `language`             | `string \| null`                 | Source language code          |
| `confidence`           | `float \| null`                  | STT confidence (0-1)          |
| `start_time`           | `float`                          | Unix timestamp (UTC)          |
| `end_time`             | `float`                          | Unix timestamp (UTC)          |
| `duration`             | `float`                          | Duration in seconds           |
| `speaker_id`           | `string \| null`                 | STT speaker ID (often null)   |
| `participant_identity` | `string \| null`                 | RTC participant identity      |
| `translations`         | `Record<string, string> \| null` | Translations by language code |
| `created_at`           | `string`                         | ISO 8601 timestamp            |

### Supported Languages

Default translation targets: `["es", "fr", "ja", "ko"]`

STT input languages: Any ISO 639-1 code supported by Cartesia/Deepgram (e.g., `"zh"`, `"en"`, `"es"`, `"fr"`, `"ja"`, `"ko"`)

---

## 5. Integration Flow

### Live Session Flow

```
┌─────────────┐    POST /enable    ┌─────────────┐
│  Frontend   │ ─────────────────▶ │   Backend   │
└─────────────┘                    └─────────────┘
       │                                  │
       │  Subscribe to "live-transcript"  │
       │ ◀────────────────────────────────│
       │        (DataChannel)             │
       │                                  │
       │   { text, language, translations │
       │     participant_identity }       │
       ▼                                  │
  Display captions with language selector │
```

### VOD/Playback Flow

```
┌─────────────┐  GET /master.m3u8  ┌─────────────┐
│  HLS Player │ ─────────────────▶ │   Backend   │
└─────────────┘                    └─────────────┘
       │                                  │
       │   M3U8 with subtitle tracks      │
       │ ◀────────────────────────────────│
       │                                  │
       │  GET /captions-{n}.vtt           │
       │ ─────────────────────────────────▶
       ▼
  Player renders subtitles from VTT segments
```

---

## 6. Error Codes

| Code                                   | HTTP | Description                  |
| -------------------------------------- | ---- | ---------------------------- |
| `E_SESSION_NOT_FOUND`                  | 404  | Session doesn't exist        |
| `E_SESSION_NOT_STARTED`                | 400  | Session hasn't started yet   |
| `E_SESSION_FORBIDDEN`                  | 403  | User lacks permission        |
| `E_INVALID_REQUEST`                    | 400  | Missing/invalid parameters   |
| `E_NO_PLAYBACK_ID`                     | 404  | No playback ID available     |
| `E_PARTICIPANT_LANGUAGE_UPDATE_FAILED` | 500  | RTC provider API error       |
