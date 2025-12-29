from pydantic import BaseModel
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
from ....domain.cbe.post.submit import submit


router = APIRouter(prefix='/cbe/post')


@router.post('/submit', response_model=ApiSuccess | ApiFailure | CorebeResult | CorebeError)
async def cbe_post_submit(
    request: Request,
    is_corebe: bool = Query(default=True),
):
    try:
        logger.debug('enter path={} method={}', request.url.path, request.method)

        ok, payload, status_code = await submit(request)

        if ok:
            return make_response(ApiSuccess(results=payload), is_corebe)

        errcode = payload.get('errcode') if isinstance(payload, dict) else None
        errmesg = payload.get('errmesg') if isinstance(payload, dict) else None
        failure = api_failure(errcode=errcode, errmesg=errmesg or 'Failed to submit post.')

        return make_response(failure, is_corebe, status_code=status_code)
    except Exception as e:
        failure = api_failure(errmesg=e)
        return make_response(failure, is_corebe)
