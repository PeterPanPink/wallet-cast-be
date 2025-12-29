import time
import traceback
import uuid
from contextlib import asynccontextmanager
from os import environ

import logfire
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import ORJSONResponse
from granian import Granian
from livekit.api.twirp_client import TwirpError
from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.api.flc.errors import app_error_handler, twirp_error_handler
from app.cw.api.utils import E_INVALID_PARAMS, api_failure, init_logger, load_routes
from app.cw.config import config
from app.cw.storage.redis import get_redis_manager
from app.schemas.init_schemas import init_schema
from app.utils.flc_errors import FlcError, FlcErrorCode


class HTTPLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):  # type: ignore
        start_time = time.time()
        request_id = str(uuid.uuid4())[:8]

        # Log the incoming request
        logger.info(f"[{request_id}] {request.method} {request.url.path}")

        try:
            # Process the request
            response = await call_next(request)

            # Calculate request duration
            process_time = (time.time() - start_time) * 1000

            # Log the response
            logger.info(
                f"[{request_id}] {request.method} {request.url.path} - "
                f"Status: {response.status_code} - "
                f"Duration: {process_time:.2f}ms"
            )

            return response

        except Exception as exc:
            # Calculate request duration
            process_time = (time.time() - start_time) * 1000

            # Log the exception with full traceback for Kibana
            logger.error(
                f"[{request_id}] Unhandled exception in {request.method} {request.url.path} - "
                f"Duration: {process_time:.2f}ms - "
                f"Error: {type(exc).__name__}: {exc}\n"
                f"Traceback:\n{traceback.format_exc()}"
            )

            # Return a proper JSON error response
            failure = api_failure(
                errcode=FlcErrorCode.E_INTERNAL_ERROR,
                errmesg=f"Internal server error (request_id: {request_id})",
            )
            return ORJSONResponse(
                status_code=500,
                content=failure.model_dump(),
            )


async def app_validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()

    logger.warning(
        "Validation error: path={} method={} errors={}",
        request.url.path,
        request.method,
        errors,
    )

    failure = api_failure(E_INVALID_PARAMS, errmesg=str(errors))

    return ORJSONResponse(status_code=422, content=failure.model_dump())


@asynccontextmanager
async def lifespan(server: FastAPI):
    init_logger()

    logger.info("Application startup...")

    server.state.redis_manager = get_redis_manager()

    # Initialize MongoDB schemas and Beanie ODM
    await init_schema()

    load_routes(server, "/api/v1")

    if config["LOGFIRE_ENABLE"].lower() == "true":
        logger.info("Logfire initializing")

        logfire.configure(
            token=config["LOGFIRE_TOKEN"],
            service_name="wallet-cast-demo",
            service_version=environ.get("BUILD_COMMIT") or "dev",
        )

        logger.info("Logfire instrument fastapi")
        logfire.instrument_fastapi(server, capture_headers=True)

        logger.info("Logfire instrument mongo")
        logfire.instrument_pymongo(capture_statement=config["DEBUG"])

        logger.info("Logfire instrument pydantic")
        logfire.instrument_pydantic()

    yield

    logger.info("Application shutdown...")

    await server.state.redis_manager.close_all()


app = FastAPI(
    version="1.0",
    title="WalletCast Demo API",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)

DEBUG = config["DEBUG"].lower() == "true"

app.add_middleware(HTTPLoggingMiddleware)

app.add_middleware(
    CORSMiddleware,  # type: ignore
    allow_origins=config["API_CORS_ORIGINS"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

session_secret = config.get("SESSION_SECRET", "dev-secret")
app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,  # type: ignore
    same_site="lax",
    https_only=not DEBUG,
)

app.add_exception_handler(RequestValidationError, app_validation_exception_handler)  # type: ignore
app.add_exception_handler(FlcError, app_error_handler)  # type: ignore
app.add_exception_handler(TwirpError, twirp_error_handler)  # type: ignore


def build_granian_kwargs():
    kwargs = {
        "interface": "asgi",
        "address": config["API_HOST"],
        "port": int(config["API_PORT"]),
        "workers": int(config["API_WORKERS"]),
        "reload": DEBUG,
    }

    return kwargs


if __name__ == "__main__":
    granian_kwargs = build_granian_kwargs()
    Granian("app.main:app", **granian_kwargs).serve()
