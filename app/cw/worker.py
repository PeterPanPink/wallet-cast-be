import time
import orjson
import threading
from typing import Any
from .api.utils import get_worker_info
from .storage.redis import get_cache_client
from .config import custom_config
from loguru import logger


worker_name, commit_id, instance_id = get_worker_info()


class WorkerData:
    """
    Singleton worker state with two-phase initialization.

    - _initialized: Set to True after __init__ runs once (constructor finished).
      Guards against repeated construction when requesting the singleton.
    - _ready: Set to True after async initialize() completes (Redis state established).
      Guards the async init path and is reset to False by clean().
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_initialized') and self._initialized:
            return

        self._redis_client = get_cache_client(custom_config.get_redis_major_label())

        self._root_key = custom_config.get_service_code()
        self._list_key = f'{self._root_key}:worker_data:$list'
        self._data_key = f'{self._root_key}:worker_data:{worker_name}:{commit_id}:{instance_id}'
        self._data_ttl = 60 * 10

        self._ready = False
        self._initialized = True

        self._identity = {
            'worker_name': worker_name,
            'commit_id': commit_id,
            'instance_id': instance_id,
        }

    async def initialize(self):
        if self._ready:
            return

        await self._set_data()

        self._ready = True

    async def _set_data(self, data: dict | None = None):
        if data is None:
            data = {}

        if not isinstance(data, dict):
            raise ValueError('Data must be a dictionary')

        data.update(self._identity)
        data['health_at'] = int(time.time() * 1000)

        pipeline = self._redis_client.pipeline()

        pipeline.sadd(self._list_key, self._data_key)
        pipeline.hset(self._data_key, mapping={k: orjson.dumps(v) for k, v in data.items()})
        pipeline.expire(self._data_key, self._data_ttl)

        await pipeline.execute()

    async def set_all(self, data: dict):
        logger.debug('Set worker data: data={}', data)
        await self._set_data(data)

    async def set(self, key: str, value: Any):
        logger.debug('Set worker data: key={} value={}', key, value)
        await self._set_data({key: value})

    async def hincr(self, key: str, amount: int = 1):
        await self._redis_client.hincrby(self._data_key, key, amount)

    async def get(self, key: str):
        return await self._redis_client.hget(self._data_key, key)

    async def get_all(self, data_key: str = None):
        if data_key is None:
            data_key = self._data_key
        
        result = await self._redis_client.hgetall(data_key)
        result = {self.decode_key(k): self.decode_value(v) for k, v in result.items()}

        queue_name = data_key.split(':')[2].replace('-', '_')
        queue_size = await self._redis_client.zcard(f'{self.root_key}:arq:{queue_name}')
        result['queue_size'] = int(queue_size) if queue_size is not None else 0

        return result

    async def get_list(self):
        members = await self._redis_client.smembers(self._list_key)
        if not members:
            return members

        # Ensure deterministic order for mapping results from pipeline
        member_list = sorted(list(members))

        # Batch-check existence of each member key
        pipeline = self._redis_client.pipeline()
        for key in member_list:
            pipeline.exists(key)
        exists_results = await pipeline.execute()

        # If pipeline didn't return a proper list (e.g., in mocked tests), skip cleanup
        if not isinstance(exists_results, (list, tuple)) or len(exists_results) != len(member_list):
            return members

        existing_members = set()
        missing_members = []
        for key, exists in zip(member_list, exists_results):
            if bool(exists):
                existing_members.add(key)
            else:
                missing_members.append(key)

        # Remove missing members from the set in one batch
        if missing_members:
            # SREM supports removing multiple members in a single call
            await self._redis_client.srem(self._list_key, *missing_members)

        return existing_members

    @property
    def list_key(self):
        return self._list_key

    @property
    def root_key(self):
        return self._root_key

    @property
    def data_key(self):
        return self._data_key

    async def clean(self):
        pipeline = self._redis_client.pipeline()
        pipeline.srem(self._list_key, self._data_key)
        pipeline.delete(self._data_key)
        await pipeline.execute()

        self._ready = False

    @staticmethod
    def decode_value(v):
        # Fast-path for primitives already in correct type
        if isinstance(v, (int, float, bool)) or v is None:
            return v

        # Bytes/bytearray: try JSON first, then UTF-8
        if isinstance(v, (bytes, bytearray)):
            try:
                return orjson.loads(v)
            except Exception:
                try:
                    return v.decode('utf-8')
                except Exception:
                    return v

        # Strings: attempt JSON parse, else return as-is
        if isinstance(v, str):
            try:
                return orjson.loads(v)
            except Exception:
                return v

        # Fallback
        return v

    @staticmethod
    def decode_key(k):
        return k.decode('utf-8') if isinstance(k, (bytes, bytearray)) else str(k)

    @staticmethod
    def encode_value(v):
        return orjson.dumps(v)

    @staticmethod
    def encode_key(k):
        return k.encode('utf-8') if isinstance(k, str) else str(k).encode('utf-8')
        

async def healthcheck(_, checking_at: int):
    worker_data = WorkerData()
    
    logger.debug('Healthcheck for worker {} at {}', worker_data.data_key, checking_at)
    await worker_data.set('checking_at', checking_at)
