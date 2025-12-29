# Update Participant Name Feature

## Overview

This feature allows guests (participants) to update their display name while in an RTC Provider session.

## Endpoint

**POST** `/flc/session/ingress/update_participant_name`

### Request Body

```json
{
  "room_id": "string", // OR "session_id": "string"
  "identity": "string", // Participant identity (must match authenticated user)
  "name": "string" // New display name
}
```

### Response

```json
{
  "results": {
    "identity": "string", // Participant identity
    "name": "string", // Updated display name
    "sid": "string" // Participant SID
  }
}
```

### Authentication

Requires a valid authentication token. The participant can only update their own display name (identity must match the authenticated user's user_id).

## Implementation Details

### Architecture Layers

The feature is implemented across multiple layers:

1. **API Layer** (`app/api/flc/routers/session_ingress.py`)

   - Endpoint: `update_participant_name()`
   - Validates user authorization
   - Ensures identity matches authenticated user

2. **Domain Layer** (`app/domain/live/session/`)

   - `SessionService.update_participant()`: Public interface
   - `IngressOperations.update_participant()`: Business logic
   - Validates session exists before updating

3. **Service Layer** (`app/services/cw_livekit.py`)

   - `LivekitService.update_participant()`: RTC Provider API wrapper (demo-safe)
   - Uses provider SDK request types in non-demo mode

4. **Schemas** (`app/api/flc/schemas/session_ingress.py`)
   - `UpdateParticipantNameIn`: Request model
   - `UpdateParticipantNameOut`: Response model

### Security

- **Identity Verification**: Participants can only update their own name
- **Session Ownership**: Works for both public and private sessions
- **Authorization**: Requires valid authentication token

## Usage Example

See `examples/update_participant_name_example.py` for complete examples.

### Quick Example

```python
import httpx

async def update_my_name():
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/flc/session/ingress/update_participant_name",
            json={
                "room_id": "my-livestream",
                "identity": "guest-123",
                "name": "John Doe"
            },
            headers={"Authorization": "Bearer YOUR_TOKEN"}
        )
        print(response.json())
```

## Events

When a participant's name is updated, the RTC Provider may emit a name-changed event to all participants in the room (provider-specific).

## Error Codes

- `E_SESSION_NOT_FOUND` (404): Session/room not found
- `E_PARTICIPANT_FORBIDDEN` (403): Attempting to update another user's name
- `E_INVALID_REQUEST` (400): Invalid request data
- `E_PARTICIPANT_UPDATE_FAILED` (500): Internal server error

## Testing

See `../../examples/update_participant_name_example.py` for testing examples.

## References

- Provider documentation is intentionally redacted in this public demo: `https://<redacted-rtc-provider-docs>`
