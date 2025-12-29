import asyncio
from arq.connections import ArqRedis
from redis.asyncio import Redis
from typing import Any, Literal
from pydantic import BaseModel, Field
from os import environ
from uuid import uuid4
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import ORJSONResponse
from functools import lru_cache
from pathlib import Path
from importlib import import_module
from loguru import logger


from .errors import E_INTERNAL, E_INVALID_PARAMS
from ..config import custom_config


def format_error(ex: BaseException) -> str:
    try:
        from traceback import TracebackException
        return ''.join(TracebackException.from_exception(ex).format())
    except Exception:
        import traceback
        return ''.join(traceback.format_exception(type(ex), ex, ex.__traceback__))


class ApiResponse(BaseModel):
    version: str | None = Field(default_factory=lambda: environ.get('BUILD_COMMIT', 'dev'))


class ApiSuccess(ApiResponse):
    success: Literal[True] = True
    results: Any = "OK"


class ApiFailure(ApiResponse):
    success: Literal[False] = False
    errcode: str = E_INTERNAL
    erresid: str = Field(default_factory=lambda: uuid4().hex[:10])
    errmesg: str = 'We are sorry, an error occurred.'


class LegacyApiError(ApiResponse):
    rc: str = 'ERR'
    error: dict


class LegacyApiResult(ApiResponse):
    rc: str = 'OK'
    result: Any


def api_failure(errcode: str = None, errmesg: Exception | str = None, *, trace: Any = None):
    import inspect
    
    if not errcode:
        errcode = ApiFailure.model_fields['errcode'].default

    if isinstance(errmesg, Exception):
        errmesg = format_error(errmesg)

    if not errmesg:
        errmesg = ApiFailure.model_fields['errmesg'].default

    failure = ApiFailure(errcode=errcode, errmesg=errmesg)

    caller_frame = inspect.stack()[1]
    module = inspect.getmodule(caller_frame.frame)
    module_name = module.__name__ if module and getattr(module, "__name__", None) else caller_frame.filename
    caller_info = f"{module_name}:{caller_frame.function}:{caller_frame.lineno}"

    logger.warning(
        f'{failure.errcode} {failure.erresid}\n{failure.errmesg} '
        f'caller={caller_info} trace={trace}'
    )

    return failure


def legacy_api_error(failure: ApiFailure | dict):
    if isinstance(failure, dict):
        return LegacyApiError(
            error=dict(
                code=failure['errcode'], 
                emsg=failure['errmesg'], 
                esid=failure['erresid']
            )
        )
    elif isinstance(failure, ApiFailure):
        return LegacyApiError(
            error=dict(
                code=failure.errcode, 
                emsg=failure.errmesg, 
                esid=failure.erresid
            )
        )
    else:
        raise ValueError(f"Invalid failure type: {type(failure)}")


def legacy_api_result(success: Any):
    if isinstance(success, ApiSuccess):
        if isinstance(success.results, BaseModel):
            return LegacyApiResult(result=success.results.model_dump())
        else:
            return LegacyApiResult(result=success.results)
    elif isinstance(success, BaseModel):
        return LegacyApiResult(result=success.model_dump())
    else:
        return LegacyApiResult(result=success)


def is_legacy_response_format(request: Request) -> bool:
    """
    Whether the caller requested the legacy response envelope.

    Supported query params (public-safe naming):
    - format=legacy
    - legacy=true|1|yes|on
    """
    fmt = (request.query_params.get("format") or "").lower().strip()
    if fmt == "legacy":
        return True

    legacy = (request.query_params.get("legacy") or "").lower().strip()
    return legacy in {"true", "yes", "on", "1"}
    

def check_error(results: ApiFailure | dict) -> tuple[bool, bool]:
    if isinstance(results, ApiFailure):
        return True, results.errcode == E_INTERNAL
    
    if isinstance(results, dict) and 'errcode' in results:
        return True, results['errcode'] == E_INTERNAL
    
    return False, False
    

def make_response(results, is_legacy: bool, *, status_code: int = None):
    if isinstance(results, Exception):
        failure = api_failure(errmesg=format_error(results))
        response = legacy_api_error(failure) if is_legacy else failure
        if status_code is None:
            status_code = 500
    else:
        is_error, is_internal = check_error(results)
        if is_error:
            response = legacy_api_error(results) if is_legacy else results
            if status_code is None:
                status_code = 500 if is_internal else 400
        else:
            response = legacy_api_result(results) if is_legacy else results
            if status_code is None:
                status_code = 200
    
    return ORJSONResponse(
        status_code=status_code, 
        content=response.model_dump() if hasattr(response, 'model_dump') else response
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    errors = exc.errors()

    logger.warning(
        "Validation error: path={} method={} errors={}",
        request.url.path, request.method, errors
    )
    
    failure = api_failure(E_INVALID_PARAMS, errmesg=str(errors))

    if is_legacy_response_format(request):
        return ORJSONResponse(
            status_code=422, 
            content={
                'rc': 'ERR',
                'error': {
                    'code': E_INVALID_PARAMS,
                    'emsg': failure.errmesg,
                    'esid': failure.erresid
                }
            }
        )
    else:
        return ORJSONResponse(status_code=422, content=failure.model_dump_json())


def load_routes(app: FastAPI, prefix: str):
    for folder in ['../api', '../../api', '../../pages']:
        load_routes_in_folder(
            app, prefix if 'api' in folder else '', 
            Path(__file__).parent / folder
        )

    for route_info in get_all_routes_info(app):
        methods = ','.join(sorted(route_info['methods']))
        logger.info('Loaded route: {:<12} {:<60} {}', methods, route_info['path'], route_info['endpoint'])


def load_routes_in_folder(app: FastAPI, prefix: str, folder: Path):
    from ..config import config
    disabled_routes = [x.strip() for x in config.get('API_DISABLED', '').split(',') if x.strip()]
    logger.debug('disabled routes: {}', disabled_routes)
    
    has_app_folder = False
    current_folder = folder
    while current_folder.parent is not None:
        current_folder = current_folder.parent
        if current_folder.name == 'app':
            has_app_folder = True
            break   
    logger.debug('has_app_folder: {}', has_app_folder)
    app_module_prefix = 'app.' if has_app_folder else ''

    for x in folder.rglob('*.py'):
        if x.name.endswith('.py') and x.name != '__init__.py':
            # Build module name by path - handle nested directories
            relative_path = x.relative_to(Path(__file__).parent)

            # Convert path separators to dots and remove .py extension
            name = str(relative_path).replace('/', '.').replace('\\', '.')[:-3]
            disabled = False
            for disabled_route in disabled_routes:
                if f'.{disabled_route}' in name:
                    logger.warning('disabled route {} in {}', disabled_route, name)
                    disabled = True
                    break
            if disabled:
                continue
            try:
                # Use absolute import by removing the leading dots

                if name.startswith('...api.'):
                    name = name.replace('...api.', f'{app_module_prefix}shared.api.', 1)
                elif name.startswith('......api.'):
                    name = name.replace('......api.', f'{app_module_prefix}api.', 1)
                elif name.startswith('......pages.'):
                    name = name.replace('......pages.', f'{app_module_prefix}pages.', 1)

                module = import_module(name)
                if hasattr(module, "router"):
                    app.include_router(module.router, prefix=prefix)
                    logger.info('Added routes in {}', name)

            except ImportError as e:
                logger.warning('Failed to import {}: {}', name, e)
                continue


def get_all_routes_info(app: FastAPI):
    routes_info = []

    for route in app.routes:
        if hasattr(route, 'methods'):
            endpoint_name = route.endpoint.__name__ if hasattr(route.endpoint, '__name__') else str(route.endpoint)
            routes_info.append(
                {
                    "methods": sorted(route.methods),
                    "path": route.path,
                    "name": route.name,
                    "endpoint": endpoint_name,
                }
            )

    return routes_info


async def verify_api_key(x_api_key: str = Header(...)):
    from ..config import config

    if x_api_key != config.get('INTERNAL_API_KEY'):
        logger.warning('Invalid API key attempt')
        raise HTTPException(status_code=401, detail='Invalid API key')


@lru_cache
def get_worker_info():
    project_root = Path(__file__).parent.parent.parent.parent
    worker_name = environ.get('WORKER_NAME', project_root.name)

    parts = environ.get('BUILD_COMMIT', '').split('-')
    commit_id = parts[1] if len(parts) > 1 else 'dev'

    return worker_name, commit_id, uuid4().hex[:8]    


def init_logger():
    import sys
    import logging
    from ..config import config

    for name in ('arq', 'arq.jobs', 'arq.connections', 'arq.worker'):
        logging.getLogger(name).setLevel(logging.ERROR)

    logger.remove()

    worker_name, commit_id, _ = get_worker_info()

    if config['DEBUG']:
        logger_level = 'DEBUG'
        logger_format = (
            f'<yellow>{worker_name}:{commit_id}</yellow> | '
            '<green>{time:MM-DD HH:mm:ss.SSS}</green> | '
            '<level>{level: <8}</level> | '
            '<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | '
            '<level>{message}</level>'
        )
    else:
        logger_level = 'INFO'
        logger_format = (
            f'{worker_name}:{commit_id} | '
            '{time:MM-DD HH:mm:ss.SSS} | '
            '{level: <8} | '
            '{name}:{function}:{line} | '
            '{message}'
        )
    logger.add(sys.stderr, level=logger_level, format=logger_format)


def log_taskgroup_errors(err: Exception):
    errors = []
    subs = getattr(err, 'exceptions', None)
    if subs and isinstance(subs, (list, tuple)):
        for idx, sub in enumerate(subs, 1):
            errors.append(f"TaskGroup sub-exception[{idx}]:\n{format_error(sub)}")
            logger.error(errors[-1])
    else:
        errors.append(f"TaskGroup error (no sub-exceptions attr): {format_error(err)}")
        logger.error(errors[-1])

    return '\n'.join(errors)


def ensure_coro(awaitable):
    """Ensure the passed awaitable is a coroutine object suitable for create_task.

    Some drivers may return Future-like objects instead of true coroutine objects.
    TaskGroup.create_task requires a coroutine, so wrap Futures into a small coroutine.
    """
    if asyncio.iscoroutine(awaitable):
        return awaitable

    async def _wrap():
        return await awaitable

    return _wrap()


def add_to_taskgroup(tg: asyncio.TaskGroup, func):
    return tg.create_task(ensure_coro(func))


async def run_taskgroup(*funcs):
    """
    Run multiple awaitables concurrently.

    Notes:
        The original codebase used `asyncio.TaskGroup` (Python 3.11+).
        For broader compatibility in this demo, we fall back to `asyncio.gather`
        when TaskGroup is not available.
    """
    if hasattr(asyncio, "TaskGroup"):
        try:
            async with asyncio.TaskGroup() as tg:  # type: ignore[attr-defined]
                for func in funcs:
                    add_to_taskgroup(tg, func)
        except Exception as tg_err:
            logger.error("Error running taskgroup: {}", tg_err)
            raise
    else:
        await asyncio.gather(*(ensure_coro(f) for f in funcs))


def get_redis_major_client(request: Request) -> Redis:
    redis_major_label = custom_config.get_redis_major_label()
    return request.app.state.redis_manager.get_cache_client(redis_major_label)


def get_redis_queue_client(request: Request) -> ArqRedis:
    redis_queue_label = custom_config.get_redis_queue_label()
    return request.app.state.redis_manager.get_queue_client(redis_queue_label)
