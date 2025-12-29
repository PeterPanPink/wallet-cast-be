from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from loguru import logger

from app.shared.api.utils import init_logger
from app.shared.config import custom_config
from app.shared.storage.mongo import get_mongo_client, get_mongo_manager
from app.shared.storage.redis import get_redis_client, get_redis_manager
from app.shared.worker import WorkerData

redis_manager = get_redis_manager()
redis_info = get_redis_manager().get_connection_info()
redis_queue_label = custom_config.get_redis_queue_label()
redis_major_label = custom_config.get_redis_major_label()

mongo_manager = get_mongo_manager()
mongo_info = get_mongo_manager().get_connection_info()

queue_url = redis_info[redis_queue_label]["original_url"]


SVC_KEY = "wallet-cast-demo"

SVC_KEY_CONFIG = f"{SVC_KEY}:config"
SVC_KEY_RECV_CS_CBE = f"{SVC_KEY}:recv_cs_cbe"
SVC_KEY_RECV_CS_LVM = f"{SVC_KEY}:recv_cs_lvm"

QUEUE_KEY = f"{SVC_KEY}:streaq"
QUEUE_KEY_API_PROBER = f"{QUEUE_KEY}:api-prober"
QUEUE_KEY_RECV_CS_CBE = f"{QUEUE_KEY}:recv_cs_cbe"
QUEUE_KEY_RECV_CS_LVM = f"{QUEUE_KEY}:recv_cs_lvm"
QUEUE_KEY_SAVE_CHANGE = f"{QUEUE_KEY}:save_change"
QUEUE_KEY_SNAPSHOT = f"{QUEUE_KEY}:snapshot"
QUEUE_KEY_TRANSFORM = f"{QUEUE_KEY}:transform"
QUEUE_KEY_TRANSFORM_SCHED = f"{QUEUE_KEY}:transform_sched"


@dataclass
class WorkerContext:
    """Type-safe context for worker tasks with Redis/Mongo clients and worker data."""

    worker_data: WorkerData
    redis_clients: dict = field(default_factory=dict)
    mongo_clients: dict = field(default_factory=dict)


def get_clients(**kwargs) -> tuple[dict, dict]:
    """Get Redis and Mongo clients based on requested labels."""
    redis_clients = {}
    mongo_clients = {}

    for label in redis_info.keys():
        if kwargs.get(label):
            redis_clients[label] = get_redis_client(label)

    for label in mongo_info.keys():
        if kwargs.get(label):
            mongo_clients[label] = get_mongo_client(label)

    return redis_clients, mongo_clients


@asynccontextmanager
async def base_lifespan(**kwargs) -> AsyncIterator[WorkerContext]:
    """Base lifespan context manager for workers."""
    init_logger()
    logger.info("Startup worker")

    redis_clients, mongo_clients = get_clients(**kwargs)

    worker_data = WorkerData()
    await worker_data.initialize()

    try:
        yield WorkerContext(
            worker_data=worker_data,
            redis_clients=redis_clients,
            mongo_clients=mongo_clients,
        )
    finally:
        logger.info("Shutdown worker")
        await worker_data.clean()
        await redis_manager.close_all()
