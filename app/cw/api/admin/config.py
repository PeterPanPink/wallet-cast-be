import time
import orjson
from pydantic import BaseModel, field_validator
from fastapi import Depends, APIRouter
from loguru import logger

from ...storage.redis import get_cache_client
from ...api.utils import ApiSuccess, ApiFailure, api_failure, verify_api_key
from ...api.errors import E_NOT_FOUND
from ...config import custom_config


router = APIRouter(prefix='/admin/config')


def get_root_key(code: str):
    return f'{custom_config.get_dynamic_config_root_key()}:{{{code}}}'


class ConfigParams(BaseModel):
    code: str
    data: dict

    @field_validator('data')
    @classmethod
    def validate_data(cls, v, values):
        root = get_root_key(values.data["code"])

        for k in v.keys():
            if not k.startswith(root):
                raise ValueError(f'Invalid config root key: {k}')
            if k == root:
                if 'hash' not in v[root]:
                    raise ValueError("Invalid root: missing 'hash'")
                if 'keys' not in v[root]:
                    raise ValueError("Invalid root: missing 'keys'")
        return v
    

@router.get('/{code}', response_model=ApiSuccess | ApiFailure)
async def admin_config_get(code: str | None = 'default', _: None = Depends(verify_api_key)):
    try:
        cache = get_cache_client(custom_config.get_redis_major_label())

        root = get_root_key(code)
        data = await cache.get(root)
        if not data:
            return api_failure(E_NOT_FOUND, errmesg=f"Config not found: {code}")
        
        data = orjson.loads(data)
        results = {root: data}
        
        for k, v in data['keys'].items():
            cache_key = f'{root}:{k}'
            if v == 'set':
                logger.debug('Getting set: {}', k)
                results[cache_key] = await cache.smembers(cache_key)
            elif v == 'list':
                logger.debug('Getting list: {}', k)
                results[cache_key] = await cache.lrange(cache_key, 0, -1)
            elif v == 'map':
                logger.debug('Getting map: {}', k)
                results[cache_key] = await cache.hgetall(cache_key)
            else:
                logger.debug('Getting str: {}', k)
                results[cache_key] = await cache.get(cache_key)

        return ApiSuccess(results=results)
    except Exception as e:
        return api_failure(errmesg=e, trace=dict(code=code))


@router.delete('/{code}', response_model=ApiSuccess | ApiFailure)
async def admin_config_delete(code: str, _: None = Depends(verify_api_key)):
    try:
        cache = get_cache_client(custom_config.get_redis_major_label())
        
        root = get_root_key(code)
        data = await cache.get(root)
        if not data:
            return api_failure(E_NOT_FOUND, errmesg=f"Config not found: {code}")

        data = orjson.loads(data)    
        pipeline = cache.pipeline()
        
        for k in data['keys']:
            cache_key = f'{root}:{k}'
            logger.info('Deleting key: {}', cache_key)
            pipeline.delete(cache_key)

        logger.info('Deleting root: {}', root)
        pipeline.delete(root)
        pipeline.delete(f'{root}_updated')

        await pipeline.execute()

        return ApiSuccess(results="OK")
    except Exception as e:
        return api_failure(errmesg=e, trace=dict(code=code))


@router.post('', response_model=ApiSuccess | ApiFailure)
async def admin_config_update(params: ConfigParams, _: None = Depends(verify_api_key)):
    try:
        cache = get_cache_client(custom_config.get_redis_major_label())
        root = get_root_key(params.code)
        pipeline = cache.pipeline()

        for k, v in params.data.items():
            pipeline.delete(k)
            if isinstance(v, dict):
                logger.info('Saving map: {} -> {}', k, v)
                if k == root:
                    pipeline.set(k, orjson.dumps(v))
                    pipeline.set(f'{k}_updated', int(time.time()))
                else:
                    pipeline.hset(k, mapping=v)
            elif isinstance(v, list):
                if k.endswith('_set'):
                    logger.info('Saving set: {} -> {}', k, v)
                    for x in v:
                        pipeline.sadd(k, x)
                else:
                    logger.info('Saving list: {} -> {}', k, v)
                    for x in v:
                        pipeline.rpush(k, x)
            else:
                logger.info('Saving str: {} -> {}', k, v)
                pipeline.set(k, v)

        await pipeline.execute()

        return ApiSuccess(results="OK")
    except Exception as e:
        return api_failure(errmesg=e, trace=dict(code=params.code))

