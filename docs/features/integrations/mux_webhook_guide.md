# Streaming Provider Webhook Integration Guide (Sanitized Demo)

This guide explains how to configure and use the webhook endpoint in the WalletCast demo backend.

## Overview

The webhook endpoint receives real-time notifications from a streaming provider about live stream events and automatically updates session statuses in the database. It includes HMAC SHA256 signature verification for security.

## Features

- ✅ HMAC SHA256 signature verification
- ✅ Timestamp validation (prevents replay attacks)
- ✅ Automatic session status updates based on live stream events
- ✅ Comprehensive error handling and logging
- ✅ Support for common live stream events

## Configuration

### 1. Set Environment Variable

Add your webhook signing secret to your `env.local` file (do not commit it):

```bash
STREAMING_WEBHOOK_SIGNING_SECRET=PLACEHOLDER_WEBHOOK_SIGNING_SECRET
```

### 2. Configure Webhook in Streaming Provider Dashboard

1. Go to your provider webhook settings: `https://<redacted-streaming-provider-dashboard>/webhooks`
2. Click "Create New Webhook"
3. Set the webhook URL to: `https://your-domain.com/api/v1/live/webhooks/mux`
4. Select the events you want to receive (recommended events below)
5. Copy the **signing secret** and add it to your `env.local` file

### Recommended Events

Subscribe to these events for complete live stream lifecycle tracking:

- ✅ `video.live_stream.created` - Stream created
- ✅ `video.live_stream.active` - Stream started (user connected)
- ✅ `video.live_stream.idle` - Stream idle (no active connection)
- ✅ `video.live_stream.recording` - Recording started
- ✅ `video.live_stream.disconnected` - Stream ended
- ✅ `video.live_stream.deleted` - Stream deleted
- ✅ `video.asset.created` - Recording asset created
- ✅ `video.asset.ready` - Recording ready for playback

## Event Processing

### Status Mapping

The webhook automatically updates session status based on these events:

| Provider Event                    | Session Status |
| -------------------------------- | -------------- |
| `video.live_stream.active`       | `LIVE`         |
| `video.live_stream.idle`         | `IDLE`         |
| `video.live_stream.disconnected` | `ENDED`        |

### Session Matching

Sessions are matched using either:

1. **Passthrough ID** (preferred): The `room_id` passed when creating the streaming session
2. **Live Stream ID**: Searching `config.egress.live_stream_id` field

## Endpoint Details

### POST `/api/v1/live/webhooks/streaming`

Receives streaming webhook events with signature verification.

**Headers:**

- `provider-signature` (required): HMAC signature for verification
  - Format: `t=1565220904,v1=20c75c1180c701ee8a796e81507cfd5c932fc17cf63a4a55566fd38da3a2d3d2`

**Request Body:**

```json
{
  "type": "video.live_stream.active",
  "id": "event_abc123",
  "created_at": "2024-01-15T10:30:00.000Z",
  "data": {
    "id": "stream_xyz789",
    "status": "active",
    "passthrough": "room_123",
    "stream_key": "abc123..."
  },
  "object": {
    "type": "live_stream",
    "id": "stream_xyz789"
  },
  "environment": {
    "name": "production",
    "id": "env_123"
  }
}
```

**Success Response:**

```json
{
  "results": {
    "event_id": "event_abc123",
    "event_type": "video.live_stream.active",
    "processing_result": {
      "processed": true,
      "action": "status_updated",
      "room_id": "room_123",
      "old_status": "idle",
      "new_status": "live",
      "live_stream_id": "stream_xyz789"
    }
  }
}
```

**Error Responses:**

Missing configuration:

```json
{
  "errcode": "E_WEBHOOK_CONFIG_MISSING",
  "errmesg": "Webhook signing secret not configured",
  "erresid": "abc123"
}
```

Invalid signature:

```json
{
  "errcode": "E_WEBHOOK_INVALID_SIGNATURE",
  "errmesg": "Invalid webhook signature",
  "erresid": "def456"
}
```

Expired timestamp:

```json
{
  "errcode": "E_WEBHOOK_SIGNATURE_ERROR",
  "errmesg": "Timestamp outside tolerance window: received=1565220904, current=1565221504, diff=600s",
  "erresid": "ghi789"
}
```

## Security

### Signature Verification

The endpoint verifies webhook authenticity using HMAC SHA256:

1. **Extract timestamp and signature** from `mux-signature` header
2. **Check timestamp tolerance** (default: 5 minutes) to prevent replay attacks
3. **Compute expected signature**:
   ```
   payload = "{timestamp}.{raw_request_body}"
   expected_signature = HMAC_SHA256(payload, signing_secret)
   ```
4. **Compare signatures** using constant-time comparison

### Best Practices

- ✅ Always verify webhook signatures in production
- ✅ Store signing secrets in environment variables (not in code)
- ✅ Use HTTPS for webhook endpoints
- ✅ Monitor failed verification attempts
- ✅ Rotate signing secrets periodically

## Testing

### Local Testing with ngrok

1. Start ngrok tunnel:

   ```bash
   ngrok http 8000
   ```

2. Update the streaming webhook URL to the ngrok URL:

   ```
   https://abc123.ngrok.io/api/v1/live/webhooks/streaming
   ```

3. Monitor logs for incoming webhooks:
   ```bash
   make local-logs
   ```

### Manual Testing

Create a test event with valid signature:

```python
import hmac
import hashlib
import time
import requests

signing_secret = "your_signing_secret"
timestamp = str(int(time.time()))

event_data = {
    "type": "video.live_stream.active",
    "id": "event_test",
    "created_at": "2024-01-15T10:30:00Z",
    "data": {
        "id": "stream_test",
        "status": "active",
        "passthrough": "test_room_123"
    },
    "object": {"type": "live_stream"},
    "environment": {"name": "test"}
}

# Create signature
import json
payload_str = json.dumps(event_data)
signed_payload = f"{timestamp}.{payload_str}"
signature = hmac.new(
    signing_secret.encode("utf-8"),
    signed_payload.encode("utf-8"),
    hashlib.sha256
).hexdigest()

# Send request
response = requests.post(
    "http://localhost:8000/api/v1/live/webhooks/streaming",
    json=event_data,
    headers={"provider-signature": f"t={timestamp},v1={signature}"}
)

print(response.json())
```

### Run Tests

```bash
# Run webhook tests
make test-fast tests/test_mux_webhook.py

# Run with coverage
pytest tests/test_mux_webhook.py -v --cov=app/api/live/webhooks
```

## Monitoring

### Log Patterns

Successful processing:

```
INFO  | Processing streaming webhook event: video.live_stream.active
INFO  | Updated session room_123 status: idle -> live
```

Invalid signature:

```
WARNING | Invalid streaming webhook signature
```

Session not found:

```
WARNING | No session found for live_stream_id=stream_xyz, passthrough=room_123
```

### Metrics to Monitor

- Webhook delivery success rate
- Signature verification failures
- Session update success rate
- Event processing latency

## Troubleshooting

### Webhook Not Received

1. Check webhook is configured in your streaming provider dashboard
2. Verify webhook URL is correct and accessible
3. Check firewall/security group settings
4. Review provider webhook delivery logs

### Signature Verification Fails

1. Verify `STREAMING_WEBHOOK_SIGNING_SECRET` matches your provider dashboard
2. Check timestamp is within 5 minutes (clock sync)
3. Ensure raw body is used for verification (not parsed JSON)
4. Review signature header format

### Session Not Updated

1. Check session exists with matching `room_id` or `live_stream_id`
2. Verify event type is mapped to status (see Status Mapping table)
3. Check the document database connection is healthy
4. Review session query logic in logs

## References

- Provider documentation is intentionally redacted in this public demo: `https://<redacted-streaming-provider-docs>`

## Example Workflow

1. **Stream Created**: User creates session → `start_live_egress()` creates a streaming session with `passthrough=room_id`
2. **User Connects**: OBS/broadcaster connects → provider sends `video.live_stream.active` webhook → Status updates to `LIVE`
3. **User Disconnects**: Broadcaster stops → provider sends `video.live_stream.disconnected` → Status updates to `ENDED`
4. **Recording Ready**: provider finishes processing → sends `video.asset.ready` → Recording available

## Code References

- Webhook endpoint: `app/api/live/webhooks/streaming.py` (sanitized path example)
- Signature verification: `verify_streaming_signature()` (sanitized name)
- Event handler: `handle_live_stream_event()`
-- Configuration: `app/app_config.py::AppEnvironConfig.STREAMING_WEBHOOK_SIGNING_SECRET` (sanitized name)
- Tests: `tests/test_mux_webhook.py`
