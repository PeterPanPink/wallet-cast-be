"""Database client helpers for application services."""

from motor.motor_asyncio import AsyncIOMotorClient

from app.shared.storage.mongo import get_mongo_client

# MongoDB label for live services
FLC_MONGO_LABEL = "flc_primary"


def get_flc_mongo_client() -> AsyncIOMotorClient:
    """Get MongoDB client for live services.

    Returns:
        AsyncIOMotorClient configured for the live database (external_live).
    """
    return get_mongo_client(FLC_MONGO_LABEL)
