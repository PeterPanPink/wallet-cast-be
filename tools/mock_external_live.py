"""
Mock implementation of the external-live service endpoints.

This FastAPI app exposes pared-down versions of the upstream routes so the demo
backend can run locally without reaching the real service:

* POST /admin/live/start
* POST /admin/live/stop

Run with granian:
    granian --interface ASGI --host 127.0.0.1 --port 18081 tools.mock_external_live:app

Then point EXTERNAL_LIVE_BASE_URL to http://127.0.0.1:18081 (e.g. in env.local / env.example).
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="external-live mock", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Health check endpoint for container orchestration."""
    return {"status": "ok", "service": "mock-external-live"}


@app.post("/api/v1/admin/live/start")
async def start_live(
    request: Request,
    x_api_key: str = Header(..., alias="x-api-key"),
):
    """Mock start live stream."""
    body = await request.json()
    print("=== POST /api/v1/admin/live/start ===")
    print(f"Request body: {body}")
    print("=" * 40)

    now = int(time.time() * 1000)
    user_id = body.get("user_id", "mock_user_id")
    channel = body.get("channel", {})
    session = body.get("session", {})

    return {
        "errcode": None,
        "errmesg": None,
        "results": {
            "post_id": f"mock_post_{int(time.time())}",
            "user_id": user_id,
            "channel_id": channel.get("channelId") or channel.get("channel_id") or "mock_channel",
            "session_id": session.get("sid") or session.get("session_id") or "mock_session",
            "title": channel.get("ttl", "Mock Live Stream"),
            "cover": channel.get("img", "https://example.com/cover.jpg"),
            "is_live": True,
            "viewers": 0,
            "started_at": now,
            "mux_stream_id": session.get("mux_stream_id", "mock_mux_stream"),
            "user_muted": False,
            "channel_muted": False,
        },
    }


@app.post("/api/v1/admin/live/stop")
async def stop_live(
    request: Request,
    x_api_key: str = Header(..., alias="x-api-key"),
):
    """Mock stop live stream."""
    body = await request.json()
    print("=== POST /api/v1/admin/live/stop ===")
    print(f"Request body: {body}")
    print("=" * 40)

    now = int(time.time() * 1000)
    return {
        "errcode": None,
        "errmesg": None,
        "results": {
            "post_id": body.get("post_id", "mock_post_id"),
            "user_id": body.get("user_id", "mock_user_id"),
            "channel_id": "mock_channel_id",
            "session_id": "mock_session_id",
            "title": "Mock Live Stream",
            "cover": "https://example.com/cover.jpg",
            "is_live": False,
            "viewers": 150,
            "started_at": now - 3600000,
            "stopped_at": now,
        },
    }


@app.post("/api/v1/admin/live/update")
async def update_live(
    request: Request,
    x_api_key: str = Header(..., alias="x-api-key"),
):
    """Mock update live stream metadata."""
    body = await request.json()
    print("=== POST /api/v1/admin/live/update ===")
    print(f"Request body: {body}")
    print("=" * 40)

    now = int(time.time() * 1000)
    return {
        "errcode": None,
        "errmesg": None,
        "results": {
            "post_id": body.get("post_id", "mock_post_id"),
            "user_id": "mock_user_id",
            "channel_id": "mock_channel_id",
            "session_id": "mock_session_id",
            "title": body.get("ttl", "Mock Live Stream"),
            "cover": body.get("img", "https://example.com/cover.jpg"),
            "is_live": True,
            "viewers": 50,
            "started_at": now - 1800000,
            "mux_stream_id": "mock_mux_stream",
        },
    }


__all__ = ["app"]
