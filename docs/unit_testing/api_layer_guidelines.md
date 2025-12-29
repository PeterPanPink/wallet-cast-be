# API Layer Unit Testing Guidelines

## Scope

Tests for FastAPI endpoints located in `app/api/`. These tests verify that your endpoints correctly handle requests, validate input, and return the expected responses.

## Key Principles

1.  **Use TestClient**: Use `fastapi.testclient.TestClient` (or `httpx.AsyncClient` for async tests) to send requests to your app.
2.  **Real Database**: Allow the app to use the test database configured via `beanie_db`.
3.  **Mock External Services**: Mock external API calls (RTC provider, streaming provider) to prevent network requests.
4.  **Dependency Overrides**: Use `app.dependency_overrides` if you need to replace a dependency (e.g., the current user).

## Standard Pattern

### 1. Setup

- Create a `TestClient` for your router or the full app.
- Use `beanie_db` and `clear_collections`.

### 2. Mocking Dependencies

If your endpoint requires authentication, you can override the `get_current_user` dependency.

```python
from app.api.v1.dependency import get_current_user

# In your test or fixture
app.dependency_overrides[get_current_user] = lambda: {"user_id": "test_user", "role": "admin"}
```

### Example

```python
import pytest
from fastapi.testclient import TestClient
from app.main import app  # or create a specific app with just your router
from app.schemas import Session

client = TestClient(app)

@pytest.mark.usefixtures("clear_collections")
async def test_create_session_endpoint(beanie_db):
    # Arrange
    payload = {
        "channel_id": "ch_123",
        "room_id": "room_123"
    }

    # Pre-create data
    await Channel(channel_id="ch_123", user_id="test_user", is_active=True).create()

    # Act
    # Mock external service calls that might happen inside the domain layer
    with patch("app.domain.live.session._sessions.LiveKitAPI") as mock_lk:
        response = client.post("/live/session/create", json=payload)

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data["results"]["session_id"] is not None

    # Verify DB
    assert await Session.find_one(Session.room_id == "room_123")
```

## Testing Webhooks

Webhooks often verify signatures. You may need to mock the signature verification or generate a valid signature.

```python
async def test_webhook_handler(beanie_db):
    # Mock the signature verification dependency if it's hard to generate a valid one
    app.dependency_overrides[verify_webhook_signature] = lambda: True

    response = client.post("/webhooks/livekit", json=event_payload)
    assert response.status_code == 200
```
