from app.shared.storage.mongo import get_mongo_client
from app.schemas.init import init_beanie_odm

FLC_MONGO_LABEL = "flc_primary"


async def init_schema():
    mongo_client = get_mongo_client(FLC_MONGO_LABEL)
    db = mongo_client.get_database()
    await init_beanie_odm(db)


if __name__ == "__main__":
    import asyncio

    asyncio.run(init_schema())
