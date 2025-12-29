# Global Unit Testing Guidelines

## Core Philosophy

- **Real Services over Mocks**: Use real MongoDB and Redis instances via fixtures. Avoid mocking database layers.
- **Isolation**: Each test must run in a clean state. Use `clear_collections` and `clean_redis_client`.
- **Async First**: Most tests will be async.
- **Mirror Structure**: Test files should mirror the `app/` directory structure.

## Running Tests

Use the Makefile command to run tests. This ensures dependencies (Mongo/Redis) are available.

```bash
# Run all tests (fast mode, no verbose output)
make test-fast

# Run specific test file
make test-fast tests/domain/live/session/test_create.py

# Run specific test case
make test-fast tests/domain/live/session/test_create.py::test_create_session
```

## Folder Structure

Mirror the application structure in the `tests/` directory.

```text
app/
├── api/
├── domain/
│   └── live/
│       └── session/
│           └── create.py
└── services/

tests/
├── api/
├── domain/
│   └── live/
│       └── session/
│           └── test_create.py  <-- Mirrors app/domain/live/session/create.py
└── services/
```

## Standard Test Pattern

### 1. Basic Async Test

Use `pytest-asyncio` and request necessary fixtures.

```python
import pytest
from app.schemas import Session

async def test_create_session_success(beanie_db, clean_redis_client):
    # Arrange
    room_id = "test-room-1"

    # Act
    # ... call your domain function ...

    # Assert
    session = await Session.find_one(Session.room_id == room_id)
    assert session is not None
    assert session.status == "waiting"
```

### 2. Database Isolation

Always ensure data is cleared between tests.

- **MongoDB**: Use `clear_collections` fixture (or `beanie_db` which initializes it, but explicit `clear_collections` is safer if you modify data).
- **Redis**: Use `clean_redis_client` (provides a flushed Redis instance).

```python
@pytest.mark.usefixtures("clear_collections")
async def test_mongo_operation(beanie_db):
    # Database is empty here
    ...
```

## Fixtures

### Using Existing Fixtures

Common fixtures are available in `tests/fixtures/` and automatically loaded via `tests/conftest.py`.

| Fixture              | Description                                                         | Scope    |
| -------------------- | ------------------------------------------------------------------- | -------- |
| `beanie_db`          | Initializes Beanie ODM with test DB. Yields `AsyncIOMotorDatabase`. | Function |
| `mongo_client`       | Raw `AsyncIOMotorClient`.                                           | Function |
| `clean_redis_client` | Redis client with `FLUSHDB` executed before test.                   | Function |
| `redis_queue_client` | Redis client for queue operations.                                  | Function |

### Creating New Fixtures

1. **Global Fixtures**: Add to `tests/fixtures/` if reusable across many modules.
   - Example: `tests/fixtures/livekit_fixtures.py`
   - Import in `tests/conftest.py` to make available globally.
2. **Module Fixtures**: Define in `conftest.py` within the specific test subdirectory (e.g., `tests/domain/conftest.py`).
3. **Local Fixtures**: Define in the test file itself if only used there.

### External Services (RTC/Streaming providers, etc.)

Do **not** make real API calls to external services in unit tests.

1. Create a fixture that mocks the service client.
2. Place it in `tests/fixtures/` (e.g., `mock_livekit.py`) if reused.
3. Use `unittest.mock` or `pytest-mock` to simulate responses.

```python
# tests/fixtures/livekit_fixtures.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_livekit_service():
    service = AsyncMock()
    service.create_room.return_value = {"room": "mock-room"}
    return service
```

## Best Practices

- **No Logic in Tests**: Tests should be declarative (Arrange-Act-Assert).
- **Test Public API**: Test the public interface of the module (e.g., domain service functions), not internal helpers.
- **One Concept per Test**: Verify one behavior or scenario per test function.
