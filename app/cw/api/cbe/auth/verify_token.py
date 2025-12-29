from fastapi import APIRouter, Request, Query, Depends
from redis.asyncio import Redis
from loguru import logger

from ...utils import ApiSuccess, ApiFailure, api_failure, make_response, CorebeResult, CorebeError, get_redis_major_client
from ....domain.cbe.auth.verify_token import verify_token


router = APIRouter(prefix='/cbe/auth')


@router.get('/verify_token', response_model=ApiSuccess | ApiFailure | CorebeResult | CorebeError)
async def cbe_auth_verify_token(
    request: Request,
    is_corebe: bool = Query(default=True),
    redis_client: Redis = Depends(get_redis_major_client),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)
        
        user_info = await verify_token(request, redis_client)
        if user_info:
            return make_response(ApiSuccess(results=user_info), is_corebe)
        else:
            failure = api_failure(errcode='E_BAD_TOKEN', errmesg='Invalid token')
            return make_response(failure, is_corebe, status_code=401)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, is_corebe)
