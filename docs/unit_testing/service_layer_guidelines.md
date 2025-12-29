# Service & Worker Layer Unit Testing Guidelines

## Scope

Tests for shared services (`app/services/`) and background workers (`app/workers/`). These components often handle infrastructure concerns like caching, queues, and external API clients.

## Key Principles

1.  **Real Redis**: Use `clean_redis_client` and `redis_queue_client` to test caching and queuing logic.
2.  **Mock External APIs**: Services wrapping RTC/Streaming/Object-Storage providers should be tested by mocking the underlying SDK calls to verify correct parameters are passed.
3.  **Worker Context**: When testing worker functions, mock the `ctx` (context) dictionary.

## Standard Pattern

### 1. Testing Services (e.g., Caching)

Use the real Redis fixture to verify that keys are set and expire correctly.

```python
import pytest
from app.services.cache_service import CacheService

async def test_cache_set_get(clean_redis_client):
    # Arrange
    service = CacheService(redis=clean_redis_client)

    # Act
    await service.set("key", "value", ttl=60)
    result = await service.get("key")

    # Assert
    assert result == "value"
    # Verify TTL
    ttl = await clean_redis_client.ttl("key")
    assert 0 < ttl <= 60
```

### 2. Testing Workers

Worker functions usually take a `ctx` argument. Mock it or construct a minimal dict.

```python
import pytest
from app.workers.transform_worker import process_transform_task

async def test_worker_task(beanie_db, clean_redis_client):
    # Arrange
    ctx = {
        "redis": clean_redis_client,
        "mongo_label": "flc_primary" # If worker uses get_mongo_client internally
    }
    job_data = {"file_id": "123"}

    # Act
    # Mock internal calls if needed
    result = await process_transform_task(ctx, job_data)

    # Assert
    assert result == "success"
```

### 3. Testing External Client Wrappers

Verify that your wrapper correctly handles SDK exceptions and formats data.

```python
from unittest.mock import AsyncMock, patch
from app.services.cw_livekit import LiveKitService

async def test_create_room_error_handling():
    # Arrange
    mock_api = AsyncMock()
    mock_api.room.create_room.side_effect = Exception("API Error")

    service = LiveKitService()  # RTC provider wrapper (demo-safe)
    service.api = mock_api  # Inject mock

    # Act & Assert
    with pytest.raises(ServiceError):
        await service.create_room("room_1")
```
