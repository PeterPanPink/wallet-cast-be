from __future__ import annotations

from fastapi import Request
from loguru import logger
import httpx
from typing import Any, Dict, Tuple

from ....config import config


LoginResult = Dict[str, Any]
LoginError = Dict[str, Any]

_FORWARDED_HEADERS = (
    'user-agent',
    'x-forwarded-for',
    'x-real-ip',
    'x-request-id',
    'accept-language',
)


async def login(request: Request) -> Tuple[bool, LoginResult | LoginError, int | None]:
    """Call core-api login API and sanitize the response."""

    logger.debug('core-api login: path={} method={}', request.url.path, request.method)

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('payload must be a JSON object')
    except Exception as exc:
        logger.warning('core-api login invalid payload: {}', exc)
        return False, {
            'errcode': 'E_INVALID_PARAMS',
            'errmesg': 'Invalid JSON payload',
        }, 422

    base_url = config.get('CORE_API_URL', '')
    if not base_url:
        logger.error('CORE_API_URL not configured')
        return False, {
            'errcode': 'E_CONFIG',
            'errmesg': 'CORE_API_URL not configured',
        }, 500

    url = f"{base_url.rstrip('/')}/u/user/v2/login"

    headers: Dict[str, str] = {'content-type': 'application/json'}
    for header in _FORWARDED_HEADERS:
        value = request.headers.get(header)
        if value:
            headers[header] = value

    timeout = httpx.Timeout(5, connect=5, read=5)

    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout) as client:
            logger.debug('calling core-api login url={}', url)
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001 - surface upstream
        logger.warning('core-api login request failed: {}', exc)
        return False, {
            'errcode': 'E_AUTH_LOGIN_FAILED',
            'errmesg': str(exc),
        }, 502

    status_code = response.status_code
    logger.debug('core-api login status={} headers={}', status_code, dict(response.headers))

    try:
        data = response.json()
    except Exception:
        text = response.text.strip()
        logger.warning('core-api login invalid json status={} text={}', status_code, text)
        return False, {
            'errcode': 'E_AUTH_LOGIN_FAILED',
            'errmesg': text or 'Invalid response from core-api',
        }, status_code if status_code >= 400 else 502

    logger.debug('core-api login body={}', data)

    if not isinstance(data, dict):
        return False, {
            'errcode': 'E_AUTH_LOGIN_FAILED',
            'errmesg': 'Unexpected response from core-api',
        }, status_code if status_code >= 400 else 502

    if status_code != 200 or data.get('rc') != 'OK':
        error = data.get('error') or {}
        errcode = error.get('code') or 'E_AUTH'
        errmesg = error.get('emsg') or 'Failed to authenticate user.'
        logger.debug('core-api login failure errcode={} errmesg={}', errcode, errmesg)
        inferred_status = 401 if errcode == 'E_AUTH' else status_code if status_code >= 400 else 400
        return False, {
            'errcode': errcode,
            'errmesg': errmesg,
        }, inferred_status

    result = data.get('result') or {}
    if not isinstance(result, dict):
        return False, {
            'errcode': 'E_AUTH_LOGIN_FAILED',
            'errmesg': 'Malformed result from core-api',
        }, 502

    user = result.get('user')
    if isinstance(user, dict):
        sanitized_user = {k: v for k, v in user.items() if v is not None}
    else:
        sanitized_user = None

    sanitized: Dict[str, Any] = {
        key: value
        for key, value in result.items()
        if value is not None and key != 'user'
    }

    if sanitized_user is not None:
        sanitized['user'] = sanitized_user

    logger.debug('core-api login success user_keys={} result_keys={}',
                 list(sanitized_user.keys()) if sanitized_user else [], list(sanitized.keys()))

    return True, sanitized, None
