import orjson
import httpx
import mmh3
import asyncio
import jwt
from time import time
from typing import Any, Dict, Optional, Tuple
from fastapi import Request
from redis.asyncio import Redis
from loguru import logger

from ....config import config, custom_config


SVC_KEY = custom_config.get_service_code()


# Simple in-process LRU with TTL (size-bound + time-bound)
_LOCAL_POS: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_LOCAL_NEG: Dict[str, float] = {}
_LOCAL_LCK: Dict[str, asyncio.Lock] = {}
_MAX_LOCAL_SIZE = 1000
_MAX_POS_TTL = 300  # seconds
_MAX_NEG_TTL = 45   # seconds

_FORWARDED_HEADERS = (
    'user-agent',
    'x-forwarded-for',
    'x-real-ip',
    'x-request-id',
    'accept-language',
)


def _trim_local_cache():
    if len(_LOCAL_POS) <= _MAX_LOCAL_SIZE:
        return
    # Drop oldest by expire_at
    for k, _ in sorted(_LOCAL_POS.items(), key=lambda kv: kv[1][0])[: len(_LOCAL_POS) - _MAX_LOCAL_SIZE]:
        _LOCAL_POS.pop(k, None)


async def verify_token(request: Request, redis_client: Redis) -> Optional[Dict[str, Any]]:
    # Extract x-app-auth header JSON and get user/token
    logger.debug('enter path={} method={}', request.url.path, request.method)
    auth_header = request.headers.get('x-app-auth') or request.headers.get('X-App-Auth')
    if not auth_header:
        logger.debug('missing x-app-auth header')
        return None

    try:
        data = orjson.loads(auth_header)
        token = data.get('token')
        payload = jwt.decode(token, options={"verify_signature": False, "verify_exp": False})
        
        # Keep only user_id, username, level
        payload['user_id'] = user_id = payload.pop('userId')
        pos_exp = int(time()) + _MAX_POS_TTL
        payload['exp'] = min(payload.pop('exp', pos_exp), pos_exp)
        payload.pop('iat')
        payload.pop('gver')
        payload.pop('cver')
    except Exception:
        logger.debug('invalid x-app-auth json')
        return None

    if not user_id or not token:
        logger.debug('missing user or token in header')
        return None

    token_hash = format(mmh3.hash128(token), '032x')
    neg_key = f'{SVC_KEY}:vtneg:{token_hash}'
    pos_key = f'{SVC_KEY}:vtpos:{token_hash}:{user_id}'

    # Negative cache check (local → redis)
    now = time()
    exp_neg = _LOCAL_NEG.get(neg_key)
    if exp_neg and exp_neg > now:
        logger.debug('neg cache local hit: {}', token_hash)
        return None
    if await redis_client.get(neg_key):
        logger.debug('neg cache redis hit: {}', token_hash)
        _LOCAL_NEG[neg_key] = now + _MAX_NEG_TTL
        return None

    # Positive cache: local first
    cached = _LOCAL_POS.get(pos_key)
    if cached and cached[0] > now:
        logger.debug('pos cache local hit: {}:{}', token_hash, user_id)
        # cached[1] is the cached object
        return cached[1]

    # Redis cache next
    packed = await redis_client.get(pos_key)
    if packed:
        try:
            obj = orjson.loads(packed)
            exp = int(obj.get('exp') or 0)
            ttl = max(0, min(_MAX_POS_TTL, exp - int(now)))
            if ttl > 0:
                _LOCAL_POS[pos_key] = (now + ttl, obj)
                _trim_local_cache()
                logger.debug('pos cache redis hit: {}:{} ttl={}', token_hash, user_id, ttl)
                return obj
        except Exception:
            pass

    # Single-flight lock per token
    lock = _LOCAL_LCK.setdefault(pos_key, asyncio.Lock())
    async with lock:
        # Recheck caches after acquiring the lock
        now = time()
        exp_neg = _LOCAL_NEG.get(neg_key)
        if exp_neg and exp_neg > now:
            return None
        cached = _LOCAL_POS.get(pos_key)
        if cached and cached[0] > now:
            return cached[1]

        # Call core-api
        base_url = config.get('CORE_API_URL', '')
        if not base_url:
            logger.warning('CORE_API_URL not configured')
            return None

        url = f"{base_url.rstrip('/')}/u/user/verify/token"

        timeout = httpx.Timeout(5, connect=2, read=5)
        headers = {'x-app-auth': auth_header}
        for header in _FORWARDED_HEADERS:
            value = request.headers.get(header)
            if value:
                headers[header] = value
        logger.debug('forward headers keys={}', list(headers.keys()))
        ok = False
        body: Optional[Dict[str, Any]] = None
        for attempt in (1, 2):
            try:
                async with httpx.AsyncClient(http2=True, timeout=timeout) as client:
                    logger.debug('calling core-api attempt={} url={}', attempt, url)
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        body = resp.json()
                        logger.debug('core-api response body={}', body)
                        ok = isinstance(body, dict) and body.get('rc') == 'OK' and body.get('result') == 'valid'
                    elif resp.status_code == 401:
                        logger.debug('core-api response 401 body={}', resp.json())
                        ok = False
                    elif resp.status_code == 429:
                        logger.debug('core-api response 429 body={}', resp.json())
                        ok = False
                    else:
                        logger.debug('core-api response status={} text={}', resp.status_code, resp.text)
                        ok = False
                break
            except Exception as e:
                if attempt == 1:
                    await asyncio.sleep(0.05)
                    continue
                logger.warning('call core-api failed: {}', e)
                ok = False

        if not ok:
            # write negative cache
            _LOCAL_NEG[neg_key] = time() + _MAX_NEG_TTL
            logger.debug('write neg cache: {} ttl={}', token_hash, _MAX_NEG_TTL)
            try:
                await redis_client.setex(neg_key, _MAX_NEG_TTL, b'1')
            except Exception:
                pass
            return None
        
        ttl = max(1, min(_MAX_POS_TTL, payload['exp'] - int(time())))
        _LOCAL_POS[pos_key] = (time() + ttl, payload)
        _trim_local_cache()
        logger.debug('write pos cache: {}:{} ttl={}', token_hash, user_id, ttl)
        try:
            await redis_client.setex(pos_key, ttl, orjson.dumps(payload))
        except Exception:
            pass

        # Return public payload (only user_id, username, level)
        return payload
