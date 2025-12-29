import time
from fastapi import Depends, APIRouter
from loguru import logger

from ...storage.redis import get_cache_client, get_queue_client
from ...api.utils import ApiSuccess, ApiFailure, api_failure, verify_api_key
from ...config import custom_config
from ...worker import WorkerData


router = APIRouter(prefix='/admin/worker')
            

@router.get(f'/data', response_model=ApiSuccess | ApiFailure)
async def admin_get_worker_data(_: None = Depends(verify_api_key)):
    try:
        worker_data = WorkerData()

        logger.debug('Loading worker data from: {}', worker_data.list_key)
        worker_keys = await worker_data.get_list()

        results = {}
        for data_key in worker_keys:
            data_key = worker_data.decode_key(data_key)

            values = await worker_data.get_all(data_key)
            if not values:
                continue

            result_key = ":".join(data_key.split(':')[2:])
            results[result_key] = values

        return ApiSuccess(results=results)
    except Exception as e:
        return api_failure(errmesg=e)


@router.get('/health/{worker_id}', response_model=ApiSuccess | ApiFailure)
async def admin_get_worker_health(worker_id: str, _: None = Depends(verify_api_key)):
    try:
        cache = get_cache_client(custom_config.get_redis_major_label())
        queue = get_queue_client(custom_config.get_redis_queue_label())
        
        service_code = custom_config.get_service_code()
        data_key = f'{service_code}:worker_data:{worker_id}'

        exists = await cache.exists(data_key)
        if not exists:
            logger.debug('Worker data not found, removing from list: {}', data_key)
            await cache.srem(f'{service_code}:worker_data:$list', data_key)
            return ApiSuccess(results=dict(health=False))

        worker_name = worker_id.split(':')[0].replace('-', '_')
        queue_name = f'{service_code}:arq:{worker_name}'

        when = int(time.time() * 1000)
        logger.debug('Enqueuing healthcheck job: queue={} worker={}', queue_name, worker_id)
        await queue.enqueue_job('healthcheck', when, _queue_name=queue_name)

        logger.debug('Loading worker health time from: {}', data_key)
        health_at = WorkerData.decode_value(await cache.hget(data_key, 'health_at'))
        health = health_at is not None and int(health_at) > when - 60 * 1000

        return ApiSuccess(results=dict(health=health))
    except Exception as e:
        return api_failure(errmesg=e, trace=dict(worker_id=worker_id))
