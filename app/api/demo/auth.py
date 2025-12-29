"""Demo endpoint for JWT token generation.

This endpoint allows easy testing of API authentication by calling
the mock core_api service to generate tokens.
"""

import httpx
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from app.shared.config import config

router = APIRouter(prefix="/live/demo/auth", tags=["Dev Only"])


@router.get("/token")
async def get_mock_auth_token(
    user_id: str = Query("test_user", description="User ID for the token"),
    pwd: str = Query("mock_password", description="Password for the user"),
) -> JSONResponse:
    """Generate a mock JWT token for API testing.

    This is a demo endpoint for testing API authentication. DO NOT use in production.
    Calls mock core_api to generate a valid token.

    Example:
        GET /demo/auth/token?user_id=test_user&pwd=mock_password

    Returns:
        The response from mock core_api login endpoint.
    """
    base_url = config.get("CORE_API_URL", "")
    if not base_url:
        return JSONResponse(
            status_code=500,
            content={"errcode": "E_CONFIG", "errmesg": "CORE_API_URL not configured"},
        )

    url = f"{base_url.rstrip('/')}/u/user/v2/login"
    payload = {"content": {"username": user_id, "pwd": pwd}}

    timeout = httpx.Timeout(5, connect=5, read=5)

    try:
        async with httpx.AsyncClient(http2=True, timeout=timeout) as client:
            response = await client.post(url, json=payload)
    except Exception as exc:
        return JSONResponse(
            status_code=502,
            content={"errcode": "E_AUTH_LOGIN_FAILED", "errmesg": str(exc)},
        )

    try:
        data = response.json()
    except Exception:
        return JSONResponse(
            status_code=502,
            content={
                "errcode": "E_AUTH_LOGIN_FAILED",
                "errmesg": "Invalid response from mock core_api",
            },
        )

    return JSONResponse(status_code=response.status_code, content=data)
