"""Beanie initialization for ODM."""

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.schemas.channel import Channel
from app.schemas.session import Session
from app.schemas.transcript import Transcript
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


async def init_beanie_odm(
    mongo_client: AsyncIOMotorClient | AsyncIOMotorDatabase,
    database_name: str | None = None,
) -> None:
    """
    Initialize Beanie ODM with all document models.

    Args:
        mongo_client: Motor client or database instance
        database_name: Database name (only needed if passing client)
    """
    if isinstance(mongo_client, AsyncIOMotorClient):
        if not database_name:
            raise FlcError(
                errcode=FlcErrorCode.E_INVALID_REQUEST,
                errmesg="database_name required when passing AsyncIOMotorClient",
                status_code=FlcStatusCode.BAD_REQUEST,
            )
        database = mongo_client[database_name]
    else:
        database = mongo_client

    await init_beanie(
        database=database,  # type: ignore[arg-type]
        document_models=[
            Channel,
            Session,
            Transcript,
        ],
    )


__all__ = ["init_beanie_odm"]
