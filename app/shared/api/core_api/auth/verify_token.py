from fastapi import APIRouter, Request, Query, Depends
from redis.asyncio import Redis
from loguru import logger

from ...utils import (
    ApiSuccess,
    ApiFailure,
    LegacyApiResult,
    LegacyApiError,
    api_failure,
    make_response,
    get_redis_major_client,
)
from ....domain.core_api.auth.verify_token import verify_token


router = APIRouter(prefix='/core_api/auth')


@router.get('/verify_token', response_model=ApiSuccess | ApiFailure | LegacyApiResult | LegacyApiError)
async def core_api_auth_verify_token(
    request: Request,
    legacy: bool = Query(default=False),
    redis_client: Redis = Depends(get_redis_major_client),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)
        
        user_info = await verify_token(request, redis_client)
        if user_info:
            return make_response(ApiSuccess(results=user_info), legacy)
        else:
            failure = api_failure(errcode='E_BAD_TOKEN', errmesg='Invalid token')
            return make_response(failure, legacy, status_code=401)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, legacy)
