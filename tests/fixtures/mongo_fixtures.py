"""MongoDB/Beanie fixtures for testing."""

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.schemas import (
    Channel,
    Session,
    Transcript,
)

# All Beanie document models
BEANIE_MODELS = [
    Channel,
    Session,
    Transcript,
]


@pytest.fixture(scope="session")
def mongo_url() -> str:
    """
    Get MongoDB URL for testing.

    Priority:
    1. MONGO_URL_CBX_LIVE (test container uses this)
    2. MONGO_URL (explicit override)
    3. config.get_mongo_url("default") (fallback)
    """
    url = os.environ.get("MONGO_URL_FLC_PRIMARY")
    if url:
        return url

    raise RuntimeError("MONGO_URL_FLC_PRIMARY environment variable not set for tests.")


@pytest.fixture(scope="session")
def test_db_name() -> str:
    """Get test database name."""
    return "beanie_test_db"


@pytest_asyncio.fixture(scope="function")
async def mongo_client(mongo_url: str) -> AsyncGenerator[AsyncIOMotorClient]:
    """Create MongoDB client for testing (function-scoped to avoid event loop issues)."""
    client: AsyncIOMotorClient = AsyncIOMotorClient(mongo_url)
    yield client
    client.close()


@pytest_asyncio.fixture(scope="function")
async def beanie_db(
    mongo_client: AsyncIOMotorClient,
    test_db_name: str,
) -> AsyncGenerator[AsyncIOMotorDatabase]:
    """
    Initialize Beanie with test database (session-scoped).

    This fixture:
    1. Connects to MongoDB
    2. Initializes Beanie with all document models
    3. Yields the database for tests
    4. Drops the test database after all tests complete
    """
    db = mongo_client[test_db_name]

    # Initialize Beanie with all document models
    await init_beanie(
        database=db,  # type: ignore[arg-type]
        document_models=BEANIE_MODELS,
    )

    yield db

    # Note: We don't drop database here since each test function gets a fresh
    # Beanie init. Use clear_collections fixture to clean data between tests.


@pytest_asyncio.fixture(autouse=False)
async def clear_collections(beanie_db: AsyncIOMotorDatabase) -> None:
    """
    Clear all collections before each test.

    Usage:
        @pytest.mark.usefixtures("clear_collections")
        async def test_something(beanie_db):
            ...

    Or set autouse=True to apply to all tests automatically.
    """
    for model in BEANIE_MODELS:
        await model.get_pymongo_collection().delete_many({})


@pytest_asyncio.fixture
async def clean_beanie_db(
    beanie_db: AsyncIOMotorDatabase,
    clear_collections: None,
) -> AsyncIOMotorDatabase:
    """
    Provide Beanie database with cleared collections.

    This combines beanie_db initialization with collection clearing,
    ensuring each test starts with empty collections.
    """
    return beanie_db
