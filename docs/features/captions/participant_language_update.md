# Participant Language Update

Allow participants to change their STT language mid-session without disrupting others.

## API Endpoint

```http
POST /flc/session/ingress/caption/update-language
```

**Request:**

```json
{
  "session_id": "sess_123",
  "participant_identity": "user_456",
  "language": "es"
}
```

**Response:**

```json
{
  "success": true,
  "participant_identity": "user_456",
  "language": "es"
}
```

## How It Works

1. API sets `stt_language` attribute on the RTC participant
2. `MultiSpeakerCaptionManager` listens for `participant_attributes_changed`
3. On language change: gracefully stops current session, restarts with new language
4. Other participants continue uninterrupted

## Attribute

| Key            | Value              | Example |
| -------------- | ------------------ | ------- |
| `stt_language` | ISO 639-1 language | `"es"`  |

## Error Codes

- `E_PARTICIPANT_LANGUAGE_UPDATE_FAILED` - RTC provider API error
