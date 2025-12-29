from fastapi import APIRouter, Query, Request
from loguru import logger

from ...utils import (
    ApiSuccess,
    ApiFailure,
    CorebeResult,
    CorebeError,
    api_failure,
    make_response,
)
from ....domain.cbe.auth.login import login


router = APIRouter(prefix='/cbe/auth')


@router.post('/login', response_model=ApiSuccess | ApiFailure | CorebeResult | CorebeError)
async def cbe_auth_login(
    request: Request,
    is_corebe: bool = Query(default=True),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)

        ok, payload, status_code = await login(request)

        if ok:
            return make_response(ApiSuccess(results=payload), is_corebe)

        errcode = payload.get('errcode') if isinstance(payload, dict) else None
        errmesg = payload.get('errmesg') if isinstance(payload, dict) else None
        failure = api_failure(errcode=errcode, errmesg=errmesg or 'Failed to authenticate user.')

        return make_response(failure, is_corebe, status_code=status_code)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, is_corebe)