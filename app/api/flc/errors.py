import inspect
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse
from livekit.api.twirp_client import TwirpError, TwirpErrorCode
from loguru import logger

from app.cw.api.utils import ApiFailure, make_response
from app.utils.flc_errors import FlcError, FlcErrorCode


def app_api_failure(
    errcode: str | None = None,
    errmesg: Exception | str | None = None,
    *,
    trace: Any = None,
) -> ApiFailure:
    """
    Create an ApiFailure with caller context from the actual call site.

    Use this instead of api_failure() to get accurate caller info in logs.
    """
    from app.cw.api.utils import format_error

    if not errcode:
        errcode = str(ApiFailure.model_fields["errcode"].default)

    if isinstance(errmesg, Exception):
        errmesg = format_error(errmesg)

    if not errmesg:
        errmesg = str(ApiFailure.model_fields["errmesg"].default)

    failure = ApiFailure(errcode=errcode, errmesg=errmesg)

    caller_frame = inspect.stack()[1]
    module = inspect.getmodule(caller_frame.frame)
    module_name = (
        module.__name__ if module and getattr(module, "__name__", None) else caller_frame.filename
    )
    caller_info = f"{module_name}:{caller_frame.function}:{caller_frame.lineno}"

    logger.warning(
        f"{failure.errcode} {failure.erresid}\n{failure.errmesg} caller={caller_info} trace={trace}"
    )

    return failure


async def app_error_handler(request: Request, exc: FlcError) -> JSONResponse:
    """
    Custom exception handler for FlcError.
    Converts FlcError to ApiFailure and returns via make_response.
    """
    # Log with the caller info captured when FlcError was raised
    log_msg = f"{exc.errcode} {exc.erresid} msg={exc.errmesg} caller={exc.caller_info}"
    if exc.errcode == FlcErrorCode.E_INTERNAL_ERROR.value:
        logger.error(log_msg)
    else:
        logger.warning(log_msg)

    failure = ApiFailure(errcode=exc.errcode, errmesg=exc.errmesg, erresid=exc.erresid)
    return make_response(failure, is_corebe=False, status_code=exc.status_code)


# Mapping from Twirp error codes to FlcErrorCode
_TWIRP_TO_FLC_ERROR_MAP = {
    TwirpErrorCode.CANCELED: FlcErrorCode.E_LIVEKIT_CANCELED,
    TwirpErrorCode.UNKNOWN: FlcErrorCode.E_LIVEKIT_UNKNOWN,
    TwirpErrorCode.INVALID_ARGUMENT: FlcErrorCode.E_LIVEKIT_INVALID_ARGUMENT,
    TwirpErrorCode.MALFORMED: FlcErrorCode.E_LIVEKIT_MALFORMED,
    TwirpErrorCode.DEADLINE_EXCEEDED: FlcErrorCode.E_LIVEKIT_DEADLINE_EXCEEDED,
    TwirpErrorCode.NOT_FOUND: FlcErrorCode.E_LIVEKIT_NOT_FOUND,
    TwirpErrorCode.BAD_ROUTE: FlcErrorCode.E_LIVEKIT_BAD_ROUTE,
    TwirpErrorCode.ALREADY_EXISTS: FlcErrorCode.E_LIVEKIT_ALREADY_EXISTS,
    TwirpErrorCode.PERMISSION_DENIED: FlcErrorCode.E_LIVEKIT_PERMISSION_DENIED,
    TwirpErrorCode.UNAUTHENTICATED: FlcErrorCode.E_LIVEKIT_UNAUTHENTICATED,
    TwirpErrorCode.RESOURCE_EXHAUSTED: FlcErrorCode.E_LIVEKIT_RESOURCE_EXHAUSTED,
    TwirpErrorCode.FAILED_PRECONDITION: FlcErrorCode.E_LIVEKIT_FAILED_PRECONDITION,
    TwirpErrorCode.ABORTED: FlcErrorCode.E_LIVEKIT_ABORTED,
    TwirpErrorCode.OUT_OF_RANGE: FlcErrorCode.E_LIVEKIT_OUT_OF_RANGE,
    TwirpErrorCode.UNIMPLEMENTED: FlcErrorCode.E_LIVEKIT_UNIMPLEMENTED,
    TwirpErrorCode.INTERNAL: FlcErrorCode.E_LIVEKIT_INTERNAL,
    TwirpErrorCode.UNAVAILABLE: FlcErrorCode.E_LIVEKIT_UNAVAILABLE,
    TwirpErrorCode.DATA_LOSS: FlcErrorCode.E_LIVEKIT_DATA_LOSS,
}


async def twirp_error_handler(request: Request, exc: TwirpError) -> JSONResponse:
    """
    Custom exception handler for TwirpError (LiveKit API errors).
    Converts TwirpError to ApiFailure and returns via make_response.
    """
    # Map Twirp error code to FlcErrorCode, default to E_INTERNAL_ERROR
    flc_errcode = _TWIRP_TO_FLC_ERROR_MAP.get(exc.code, FlcErrorCode.E_INTERNAL_ERROR)

    log_msg = f"TwirpError: code={exc.code} status={exc.status} msg={exc.message}"
    if exc.metadata:
        log_msg += f" metadata={exc.metadata}"

    if exc.status >= 500:
        logger.error(log_msg)
    else:
        logger.warning(log_msg)

    failure = ApiFailure(errcode=flc_errcode.value, errmesg=exc.message)
    return make_response(failure, is_corebe=False, status_code=exc.status)
