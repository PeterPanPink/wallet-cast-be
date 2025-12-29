from __future__ import annotations

from typing import Tuple, Dict, Any

import httpx
from fastapi import Request
from loguru import logger

from ....config import config


SubmitResult = Dict[str, Any]
SubmitError = Dict[str, Any]

_FORWARDED_HEADERS = (
    'user-agent',
    'x-forwarded-for',
    'x-real-ip',
    'x-request-id',
    'accept-language',
    'x-app-auth',
    'x-app-platform',
    'x-app-version',
    'x-app-device',
)


async def submit(request: Request) -> Tuple[bool, SubmitResult | SubmitError, int | None]:
    """Call core-be /u/post to create a post and return the response."""

    logger.debug('core-be post submit: path={} method={}', request.url.path, request.method)

    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise ValueError('payload must be a JSON object')
    except Exception as exc:
        logger.warning('core-be post submit invalid payload: {}', exc)
        return False, {
            'errcode': 'E_INVALID_PARAMS',
            'errmesg': 'Invalid JSON payload',
        }, 422

    base_url = config.get('COREBE_API_URL', '')
    if not base_url:
        logger.error('COREBE_API_URL not configured')
        return False, {
            'errcode': 'E_CONFIG',
            'errmesg': 'COREBE_API_URL not configured',
        }, 500

    url = f"{base_url.rstrip('/')}/u/post"

    headers: Dict[str, str] = {'content-type': 'application/json'}
    for header in _FORWARDED_HEADERS:
        value = request.headers.get(header)
        if value:
            headers[header] = value

    timeout = httpx.Timeout(10.0, connect=5.0, read=10.0)

    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout) as client:
            logger.debug('calling core-be post submit url={}', url)
            response = await client.post(url, json=payload, headers=headers)
    except Exception as exc:  # noqa: BLE001 - surface upstream
        logger.warning('core-be post submit request failed: {}', exc)
        return False, {
            'errcode': 'E_POST_SUBMIT_FAILED',
            'errmesg': str(exc),
        }, 502

    status_code = response.status_code
    logger.debug('core-be post submit status={} headers={}', status_code, dict(response.headers))

    try:
        data = response.json()
    except Exception:
        text = response.text.strip()
        logger.warning('core-be post submit invalid json status={} text={}', status_code, text)
        return False, {
            'errcode': 'E_POST_SUBMIT_FAILED',
            'errmesg': text or 'Invalid response from core-be',
        }, status_code if status_code >= 400 else 502

    logger.debug('core-be post submit body={}', data)

    if 200 <= status_code < 300:
        return True, data['result'], None

    errcode = data.get('errcode') if isinstance(data, dict) else None
    errmesg = data.get('errmesg') if isinstance(data, dict) else None
    if isinstance(data, dict):
        error = data.get('error')
        if isinstance(error, dict):
            errcode = errcode or error.get('code')
            errmesg = errmesg or error.get('emsg')

    return False, {
        'errcode': errcode or 'E_POST_SUBMIT_FAILED',
        'errmesg': errmesg or 'Failed to submit post.',
    }, status_code
