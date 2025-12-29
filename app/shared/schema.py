from pymongo.errors import OperationFailure
from loguru import logger

from .api.utils import format_error
from .storage.mongo import get_mongo_client
from .storage.redis import get_redis_client
from .lock import LockManager
from .config import custom_config


class SchemaManager:
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if not self._initialized:
            # collections keyed by mongo label -> collection name -> definition
            self._collections: dict[str, dict[str, dict]] = {}
            SchemaManager._initialized = True

    def register_collection(self, mongo_label: str, collection_name: str, schema: dict) -> None:
        collections_for_label = self._collections.setdefault(mongo_label, {})
        collections_for_label[collection_name] = schema

    async def create_schema(self, mongo_label: str) -> None:
        service_code = custom_config.get_service_code()
        redis_major_label = custom_config.get_redis_major_label()

        redis_client = get_redis_client(redis_major_label)
        lm = LockManager(redis_client, fence_prefix=service_code, default_ttl=30)
        ok = await lm.acquire('create_schema', blocking=False, auto_renew=True)
        if not ok:
            return

        try:
            collections = self._collections.get(mongo_label, {})
            if not collections:
                logger.debug("No collections registered for mongo label {}", mongo_label)
                return

            for collection_name in collections:
                await self.create_collection(mongo_label, collection_name)
        except Exception as e:
            logger.error("Failed to create schema: {}", format_error(e))
        finally:
            await lm.release()

    async def create_collection(self, mongo_label: str, collection_name: str) -> None:
        collections = self._collections.get(mongo_label)
        if not collections or collection_name not in collections:
            logger.error("Collection {} not registered for mongo label {}", collection_name, mongo_label)
            return

        client = get_mongo_client(mongo_label)
        db = client.get_database()
        collection = db[collection_name]
        definition = collections[collection_name]

        index_info = await collection.index_information()
        has_idx_named = any(name.startswith('idx_') for name in index_info.keys())

        if len(index_info) > 0:
            if not has_idx_named:
                logger.debug("Collection {} already initialized, but lacks idx_* indexes: {}", collection_name, index_info)
                return
            else:
                logger.debug("Collection {} already initialized, existing indexes: {}", collection_name, index_info)
                return

        if "shard_key" in definition:
            try:
                await client.admin.command('shardCollection', f"{db.name}.{collection_name}", key=definition["shard_key"])
                logger.info("Sharded collection: {}", collection_name)
            except OperationFailure as e:
                error_str = str(e)
                if "already sharded" in error_str:
                    logger.info("Collection is already sharded: {}", collection_name)
                elif "no such command" in error_str:
                    logger.error("Need to enable sharding for database: {}", db.name)
                    return
            except Exception as e:
                logger.error("Failed to shard collection: {}: {}", collection_name, e)
                return

        for index in definition["indexes"]:
            options = dict(background=True)

            if "name" in index:
                options["name"] = index["name"]

            if "partialFilterExpression" in index:
                options["partialFilterExpression"] = index["partialFilterExpression"]

            if "unique" in index:
                options["unique"] = index["unique"]

            if "expireAfterSeconds" in index:
                options["expireAfterSeconds"] = index["expireAfterSeconds"]

            await collection.create_index(index["keys"], **options)
            logger.info("Created index for {}: {}", collection_name, index)


# Expose a single shared instance (singleton)
schema_manager = SchemaManager()

__all__ = [
    "SchemaManager",
    "schema_manager",
]
    
