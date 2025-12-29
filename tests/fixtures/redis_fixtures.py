"""Redis fixtures for testing."""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from redis.asyncio import Redis


@pytest.fixture(scope="session")
def redis_url() -> str:
    """
    Get Redis URL for testing.

    Priority:
    1. REDIS_URL_FLC_MAJOR (test container uses this)
    2. config.get_redis_url("default") (fallback)
    """
    url = os.environ.get("REDIS_URL_FLC_MAJOR")
    if url:
        return url

    raise RuntimeError("REDIS_URL_FLC_MAJOR environment variable not set for tests.")


@pytest.fixture(scope="session")
def redis_queue_url() -> str:
    """
    Get Redis queue URL for testing.

    Priority:
    1. REDIS_URL_FLC_QUEUE (test container uses this)
    2. config.get_redis_url("default") (fallback)
    """
    url = os.environ.get("REDIS_URL_FLC_QUEUE")
    if url:
        return url

    raise RuntimeError("REDIS_URL_FLC_QUEUE environment variable not set for tests.")


@pytest_asyncio.fixture(scope="function")
async def redis_client(redis_url: str) -> AsyncGenerator[Redis]:
    """
    Create Redis client for testing (function-scoped to avoid event loop issues).

    This fixture:
    1. Connects to Redis
    2. Yields the client for tests
    3. Closes the client after the test completes
    """
    client: Redis = Redis.from_url(redis_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(scope="function")
async def redis_queue_client(redis_queue_url: str) -> AsyncGenerator[Redis]:
    """
    Create Redis queue client for testing (function-scoped to avoid event loop issues).

    This fixture:
    1. Connects to Redis queue
    2. Yields the client for tests
    3. Closes the client after the test completes
    """
    client: Redis = Redis.from_url(redis_queue_url, decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture(autouse=False)
async def clear_redis(redis_client: Redis) -> None:
    """
    Clear all keys in Redis before each test.

    WARNING: This will FLUSHDB the current database. Only use in test environments.

    Usage:
        @pytest.mark.usefixtures("clear_redis")
        async def test_something(redis_client):
            ...

    Or set autouse=True to apply to all tests automatically.
    """
    await redis_client.flushdb()


@pytest_asyncio.fixture
async def clean_redis_client(
    redis_client: Redis,
    clear_redis: None,
) -> Redis:
    """
    Provide Redis client with cleared database.

    This combines redis_client initialization with database clearing,
    ensuring each test starts with an empty Redis database.
    """
    return redis_client
