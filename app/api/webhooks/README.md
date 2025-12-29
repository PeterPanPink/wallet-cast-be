# Webhooks

This directory contains webhook endpoints for external service integrations.

## LiveKit Webhook

**Endpoint:** `POST /api/v1/webhooks/livekit`

Receives real-time notifications from LiveKit about room and participant events.

### Configuration

Add your RTC provider credentials to `env.local` (do not commit):

```bash
LIVEKIT_URL=wss://your-livekit-server.com
LIVEKIT_API_KEY=your_api_key
LIVEKIT_API_SECRET=your_api_secret
```

### Configure in LiveKit

When self-hosting LiveKit, add to your `config.yaml`:

```yaml
webhook:
  api_key: "your_api_key" # Must match LIVEKIT_API_KEY
  urls:
    - "https://your-domain.com/api/v1/webhooks/livekit"
```

For LiveKit Cloud, configure in your project's dashboard Settings → Webhooks.

### Security

- Uses JWT signature verification with sha256 payload hash
- Requires valid Authorization header from LiveKit
- Validates requests using LiveKit's WebhookReceiver

### Event Processing

The webhook automatically updates session status based on these events:

| LiveKit Event   | Session Status |
| --------------- | -------------- |
| `room_started`  | `LIVE`         |
| `room_finished` | `STOPPED`      |

Other events are logged but don't trigger status changes:

- `participant_joined`
- `participant_left`
- `participant_connection_aborted`
- `track_published`
- `track_unpublished`
- `egress_started/updated/ended`
- `ingress_started/ended`

### Testing

Use the test script to verify the webhook:

```bash
# Make sure the server is running
uv run python -m app.main

# In another terminal, run the test script
uv run python tools/test_livekit_webhook.py
```

### Response Format

**Success:**

```json
{
  "success": true,
  "results": {
    "processed": true,
    "action": "status_updated",
    "room_id": "room_123",
    "old_status": "ready",
    "new_status": "live",
    "event_type": "room_started"
  }
}
```

**Error:**

```json
{
  "success": false,
  "errcode": "E_WEBHOOK_INVALID_SIGNATURE",
  "erresid": "a1b2c3d4e5",
  "errmesg": "Webhook verification failed: hash mismatch"
}
```
