from pydantic import BaseModel
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
from ....domain.core_api.post.submit import submit


router = APIRouter(prefix='/core_api/post')


@router.post('/submit', response_model=ApiSuccess | ApiFailure | LegacyApiResult | LegacyApiError)
async def core_api_post_submit(
    request: Request,
    legacy: bool = Query(default=False),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)

        ok, payload, status_code = await submit(request)

        if ok:
            return make_response(ApiSuccess(results=payload), legacy)

        errcode = payload.get('errcode') if isinstance(payload, dict) else None
        errmesg = payload.get('errmesg') if isinstance(payload, dict) else None
        failure = api_failure(errcode=errcode, errmesg=errmesg or 'Failed to submit post.')

        return make_response(failure, legacy, status_code=status_code)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, legacy)
