from fastapi import APIRouter, Query, Request
from loguru import logger

from ...utils import (
    ApiSuccess,
    ApiFailure,
    LegacyApiResult,
    LegacyApiError,
    api_failure,
    make_response,
)
from ....domain.core_api.auth.login import login


router = APIRouter(prefix='/core_api/auth')


@router.post('/login', response_model=ApiSuccess | ApiFailure | LegacyApiResult | LegacyApiError)
async def core_api_auth_login(
    request: Request,
    legacy: bool = Query(default=False),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)

        ok, payload, status_code = await login(request)

        if ok:
            return make_response(ApiSuccess(results=payload), legacy)

        errcode = payload.get('errcode') if isinstance(payload, dict) else None
        errmesg = payload.get('errmesg') if isinstance(payload, dict) else None
        failure = api_failure(errcode=errcode, errmesg=errmesg or 'Failed to authenticate user.')

        return make_response(failure, legacy, status_code=status_code)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, legacy)