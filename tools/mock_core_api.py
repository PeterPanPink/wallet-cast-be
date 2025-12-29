"""
Mock implementation of the core API authentication endpoints.

This FastAPI app exposes pared-down versions of the upstream routes so the demo
backend can run locally without reaching a real upstream service:

* POST /u/user/v2/login        - consumes {"content": {...}} and returns mock auth data
* GET  /u/user/verify/token    - evaluates the provided x-app-auth header

Run with granian:
    granian --interface ASGI --host 127.0.0.1 --port 18080 tools.mock_core_api:app

Then point CORE_API_URL to http://127.0.0.1:18080 (e.g. in env.local / env.example).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time

import orjson
from fastapi import FastAPI, Header, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

app = FastAPI(title="core-api mock", version="0.3.0")

# JWT configuration for mock tokens (demo placeholder)
_JWT_SECRET = "PLACEHOLDER_JWT_SECRET"
_JWT_ALGORITHM = "HS256"


def _base64url_encode(data: bytes) -> str:
    """Base64url encode without padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _generate_mock_jwt(
    user_id: str, username: str, level: int = 5, ttl_seconds: int = 315360000
) -> str:
    """Generate a mock JWT token for testing.

    Args:
        user_id: The user ID
        username: The username
        level: User level (default: 5)
        ttl_seconds: Time to live in seconds (default: ~10 years)

    Returns:
        JWT token string
    """
    now = int(time.time())

    header = {"alg": _JWT_ALGORITHM, "typ": "JWT"}
    payload = {
        "userId": user_id,
        "username": username,
        "level": level,
        "gver": "2E65918F",
        "cver": "95ZS11",
        "iat": now,
        "exp": now + ttl_seconds,
    }

    header_b64 = _base64url_encode(orjson.dumps(header))
    payload_b64 = _base64url_encode(orjson.dumps(payload))

    signing_input = f"{header_b64}.{payload_b64}"
    signature = hmac.new(
        _JWT_SECRET.encode("utf-8"),
        signing_input.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    signature_b64 = _base64url_encode(signature)

    return f"{signing_input}.{signature_b64}"


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Generate mock login response for other users
def _load_mock_login_response(username: str):
    """Generate a mock login response for the given username."""
    token = _generate_mock_jwt(username, username)
    return {
        "_t": "xresp",
        "rc": "OK",
        "result": {
            "user": {
                "udate": 1764107419779,
                "_t": "uinf",
                "_id": username,
                "nickname": username,
                "email": f"{username}@mock.local",
                "username": username,
                "ousername": username,
                "status": "a",
                "lv_configs": {},
                "streaming": {},
                "lstlivedate": 1764107152405,
                "cdate": 1763015370640,
                "lang": "en",
                "infl": 5,
                "roles": {"infl": {"lvl": 5}, "liveusr": {}, "maliveusr": {}},
                "flw": 6,
                "flg": 2,
                "xversion": "271210908",
            },
            "token": token,
            "rtoken": token,
        },
    }


@app.get("/health")
async def health():
    """Health check endpoint for container orchestration."""
    return {"status": "ok", "service": "mock-core_api"}


class LoginContent(BaseModel):
    username: str = Field(..., min_length=1)
    pwd: str = Field(..., min_length=1)


class LoginRequest(BaseModel):
    content: LoginContent


@app.post("/u/user/v2/login")
async def login(body: LoginRequest):
    """Issue a mock token for any username."""
    username = body.content.username
    return _load_mock_login_response(username)


def _verify_error_response(message: str):
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "version": "dev",
            "rc": "ERR",
            "error": {
                "code": "E_BAD_TOKEN",
                "emsg": message,
                "esid": "a3114ec0d7",
            },
        },
    )


@app.get("/u/user/verify/token")
async def verify_token(x_app_auth: str | None = Header(default=None, alias="x-app-auth")):
    """Return a canned response based on the username contained in x-app-auth."""
    if not x_app_auth:
        return _verify_error_response("Invalid token: missing x-app-auth header")

    try:
        auth_payload = orjson.loads(x_app_auth)
    except orjson.JSONDecodeError:
        return _verify_error_response("Invalid token: cannot load json")

    username = auth_payload.get("user")
    if not isinstance(username, str) or not username or username == "invalid_user":
        return _verify_error_response("Invalid token: bad username")

    return {
        "version": "dev",
        "rc": "OK",
        "result": "valid",
    }


@app.post("/u/post")
async def post(x_app_auth: str | None = Header(default=None, alias="x-app-auth")):
    return {
        "version": "dev",
        "rc": "OK",
        "result": {
            "data": {
                "acl": {"_t": "acl"},
                "txt": "a post\n",
                "rich_txt": {"ops": [{"insert": "a post"}, {"insert": "\n"}]},
                "htgs": None,
                "utgs": [],
                "vtgs": [],
                "sound_ids": [],
                "sticker_ids": [],
                "txt_lang": "en",
                "_t": "post",
                "uid": "test_user",
                "cdate": 1761989301175,
                "udate": 1761989301175,
                "_id": "pfarta42b",
            },
            "aux": {"rateLimit": {"min": 999999998, "day": 999999998}},
            "serial": "post",
        },
    }


__all__ = ["app"]
