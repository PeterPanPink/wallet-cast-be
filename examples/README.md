# External RTC Provider Integration Examples (Sanitized Demo)

This directory contains examples demonstrating how the backend integrates with an external RTC provider.
For this public demo, **all provider endpoints and secrets are placeholders**.

## Prerequisites

1. **Install dependencies:**

   ```fish
   uv sync
   # Note: provider SDK installation is intentionally omitted in this public demo.
   ```

2. **Configure environment variables (demo-safe):**

   Use `env.example` as a reference (do not commit `env.local`):

   ```env
   RTC_PROVIDER_URL=https://<redacted-rtc-provider>
   RTC_PROVIDER_API_KEY=PLACEHOLDER_RTC_PROVIDER_API_KEY
   RTC_PROVIDER_API_SECRET=PLACEHOLDER_RTC_PROVIDER_API_SECRET
   ```

## Examples

### 1. Token Generation (`livekit_token_example.py`)

Generate JWT access tokens for clients to join RTC rooms.

```fish
uv run python examples/livekit_token_example.py
```

**What it demonstrates:**

- Basic token generation for a specific room
- Tokens with custom metadata
- Permission-restricted tokens (e.g., subscriber-only)
- Tokens that can join any room

### 2. Room Management API (`livekit_api_example.py`)

Use the RTC provider API wrapper to manage rooms and participants.

```fish
uv run python examples/livekit_api_example.py
```

**What it demonstrates:**

- Listing all active rooms
- Creating new rooms with configuration
- Listing participants in a room
- Getting room information
- Deleting rooms

### 3. Room Metadata Update (`livekit_room_metadata_example.py`)

Update room metadata via the API endpoint to control shared state.

```fish
uv run python examples/livekit_room_metadata_example.py
```

**What it demonstrates:**

- Updating room metadata via HTTP POST endpoint
- Sending layout mode and theme settings
- Managing complex metadata structures
- Handling API responses and errors

## Integration with API Endpoints

To use the RTC provider wrapper in your API endpoints:

```python
from fastapi import APIRouter
from app.services.integrations.livekit_service import livekit_service
from app.shared.api.utils import ApiSuccess, ApiFailure

router = APIRouter()

@router.post("/join-room")
async def join_room(identity: str, room: str):
    """Generate a token for a user to join a room."""
    try:
        token = livekit_service.create_access_token(
            identity=identity,
            room=room,
            name=identity,  # Or fetch from user database
        )
        return ApiSuccess(results={"token": token, "url": "https://<redacted-rtc-provider>"})
    except Exception as e:
        return ApiFailure(errcode="TOKEN_GENERATION_FAILED", errmesg=str(e))
```

## Provider-hosted options (redacted)

If you don't have a self-hosted RTC server, you can use a provider-hosted option:

1. Sign up at `https://<redacted-rtc-provider-hosted>`
2. Create a project and get your credentials
3. Use the provided URL/API credentials in your `env.local` file (do not commit it)

## References

- Provider documentation is intentionally redacted in this public demo: `https://<redacted-rtc-provider-docs>`
