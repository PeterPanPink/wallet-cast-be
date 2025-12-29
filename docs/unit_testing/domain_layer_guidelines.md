# Domain Layer Unit Testing Guidelines

## Scope

Tests for business logic located in `app/domain/`. These tests verify that your service methods correctly manipulate data, handle state transitions, and enforce business rules.

## Key Principles

1.  **Real Database**: Use the `beanie_db` fixture to interact with a real (test) MongoDB instance.
2.  **Mock External Services**: Do not make real calls to RTC/Streaming/Object-Storage providers. Mock these interactions.
3.  **Test Public Methods**: Focus on testing the public methods of your Service/Operations classes.

## Standard Pattern

### 1. Setup

- Import your domain service.
- Use `beanie_db` to ensure the database is ready.
- Use `clear_collections` to ensure a clean slate.

### 2. Mocking External Dependencies

If your domain service calls external providers (RTC/streaming), use `unittest.mock.patch` or `pytest-mock` to intercept these calls.

### Example

```python
import pytest
from unittest.mock import AsyncMock, patch
from app.domain.live.session.session_domain import SessionService
from app.schemas import Session, SessionState

@pytest.mark.usefixtures("clear_collections")
async def test_create_session_success(beanie_db):
    # Arrange
    service = SessionService()
    params = SessionCreateParams(
        channel_id="ch_123",
        user_id="user_123",
        room_id="room_123"
    )

    # Pre-create necessary data (e.g. Channel)
    await Channel(channel_id="ch_123", user_id="user_123", is_active=True).create()

    # Act
    # Mock any external call if create_session makes one (e.g. to an RTC provider)
    with patch("app.domain.live.session._sessions.some_external_call", new_callable=AsyncMock) as mock_ext:
        result = await service.create_session(params)

    # Assert
    assert result.session_id is not None
    assert result.status == SessionState.READY

    # Verify DB state
    saved_session = await Session.find_one(Session.session_id == result.session_id)
    assert saved_session is not None
```

## Common Scenarios

### Testing State Transitions

Verify that invalid transitions raise appropriate errors.

```python
async def test_invalid_transition(beanie_db):
    service = SessionService()
    # ... create session in STOPPED state ...

    with pytest.raises(ValueError, match="Invalid state transition"):
        await service.update_session_state(session_id, SessionState.LIVE)
```

### Testing Data Retrieval

Verify that `NotFoundError` is raised when data doesn't exist.

```python
async def test_get_session_not_found(beanie_db):
    service = SessionService()
    with pytest.raises(NotFoundError):
        await service.get_session("non_existent_id")
```
