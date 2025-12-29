"""Unit tests for session viewer router endpoints.

Tests for public/unauthenticated endpoints that allow viewers to access
playback URLs for live streams and VOD content.
"""

from datetime import datetime, timezone

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api.flc.errors import app_error_handler
from app.api.flc.routers.session_viewer import router
from app.schemas import Session, SessionState
from app.schemas.session_runtime import SessionRuntime
from app.utils.flc_errors import FlcError


@pytest.fixture
def test_app() -> FastAPI:
    """Create FastAPI test app with router and error handler."""
    app = FastAPI()
    app.add_exception_handler(FlcError, app_error_handler)  # type: ignore[arg-type]
    app.include_router(router)
    return app


@pytest_asyncio.fixture
async def client(test_app: FastAPI):
    """Create async HTTP client for testing."""
    transport = ASGITransport(app=test_app)  # type: ignore[arg-type]
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.usefixtures("clear_collections")
class TestGetPlaybackUrl:
    """Tests for GET /flc/session/viewer/get_playback_url endpoint."""

    async def test_get_playback_url_live_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return live playback URL for an active live session."""
        # Arrange
        post_id = "post_live_123"
        live_url = "https://stream.mux.com/live123.m3u8"

        runtime = SessionRuntime(
            live_playback_url=live_url,
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_live_123",
            room_id="room_live_123",
            channel_id="ch_123",
            user_id="user_123",
            status=SessionState.LIVE,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["playback_url"] == live_url
        assert data["results"]["is_live"] is True

    async def test_get_playback_url_vod_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return VOD playback URL for a stopped session."""
        # Arrange
        post_id = "post_vod_456"
        vod_url = "https://stream.mux.com/vod456.m3u8"

        runtime = SessionRuntime(
            live_playback_url="https://stream.mux.com/live456.m3u8",
            vod_playback_url=vod_url,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_vod_456",
            room_id="room_vod_456",
            channel_id="ch_456",
            user_id="user_456",
            status=SessionState.STOPPED,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["playback_url"] == vod_url
        assert data["results"]["is_live"] is False

    async def test_get_playback_url_session_not_found(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 when session with post_id doesn't exist."""
        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": "nonexistent_post"},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_SESSION_NOT_FOUND"
        assert "nonexistent_post" in data["errmesg"]

    async def test_get_playback_url_no_live_url(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 when live session has no live playback URL."""
        # Arrange
        post_id = "post_no_live_url"

        runtime = SessionRuntime(
            live_playback_url=None,  # Missing live URL
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_no_live_url",
            room_id="room_no_live_url",
            channel_id="ch_789",
            user_id="user_789",
            status=SessionState.LIVE,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_NO_LIVE_URL"
        assert "sess_no_live_url" in data["errmesg"]

    async def test_get_playback_url_no_vod_url(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 when stopped session has no VOD URL."""
        # Arrange
        post_id = "post_no_vod_url"

        runtime = SessionRuntime(
            live_playback_url="https://stream.mux.com/live.m3u8",
            vod_playback_url=None,  # Missing VOD URL
            post_id=post_id,
        )

        session = Session(
            session_id="sess_no_vod_url",
            room_id="room_no_vod_url",
            channel_id="ch_101",
            user_id="user_101",
            status=SessionState.STOPPED,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_NO_VOD_URL"
        assert "sess_no_vod_url" in data["errmesg"]

    async def test_get_playback_url_idle_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 for IDLE session (no VOD URL available)."""
        # Arrange
        post_id = "post_idle"

        runtime = SessionRuntime(
            live_playback_url=None,
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_idle",
            room_id="room_idle",
            channel_id="ch_202",
            user_id="user_202",
            status=SessionState.IDLE,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_NO_VOD_URL"

    async def test_get_playback_url_ready_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 for READY session (not yet live, no VOD)."""
        # Arrange
        post_id = "post_ready"

        runtime = SessionRuntime(
            live_playback_url=None,
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_ready",
            room_id="room_ready",
            channel_id="ch_303",
            user_id="user_303",
            status=SessionState.READY,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_NO_VOD_URL"

    async def test_get_playback_url_publishing_session_with_live_url(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return live URL for PUBLISHING session (stream started but not confirmed)."""
        # Arrange
        post_id = "post_publishing"
        live_url = "https://stream.mux.com/publishing.m3u8"

        runtime = SessionRuntime(
            live_playback_url=live_url,
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_publishing",
            room_id="room_publishing",
            channel_id="ch_404",
            user_id="user_404",
            status=SessionState.PUBLISHING,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        # PUBLISHING is not LIVE, so it should look for VOD URL which is None
        assert data["errcode"] == "E_NO_VOD_URL"

    async def test_get_playback_url_ending_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return live URL for ENDING session (still considered live)."""
        # Arrange
        post_id = "post_ending"
        live_url = "https://stream.mux.com/live_ending.m3u8"

        runtime = SessionRuntime(
            live_playback_url=live_url,
            vod_playback_url="https://stream.mux.com/ending.m3u8",
            post_id=post_id,
        )

        session = Session(
            session_id="sess_ending",
            room_id="room_ending",
            channel_id="ch_505",
            user_id="user_505",
            status=SessionState.ENDING,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["playback_url"] == live_url
        assert data["results"]["is_live"] is True

    async def test_get_playback_url_cancelled_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 404 for CANCELLED session (no VOD available)."""
        # Arrange
        post_id = "post_cancelled"

        runtime = SessionRuntime(
            live_playback_url=None,
            vod_playback_url=None,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_cancelled",
            room_id="room_cancelled",
            channel_id="ch_606",
            user_id="user_606",
            status=SessionState.CANCELLED,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 404
        data = response.json()
        assert data["success"] is False
        assert data["errcode"] == "E_NO_VOD_URL"

    async def test_get_playback_url_aborted_session(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return VOD URL for ABORTED session if available."""
        # Arrange
        post_id = "post_aborted"
        vod_url = "https://stream.mux.com/aborted.m3u8"

        runtime = SessionRuntime(
            live_playback_url="https://stream.mux.com/live_aborted.m3u8",
            vod_playback_url=vod_url,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_aborted",
            room_id="room_aborted",
            channel_id="ch_707",
            user_id="user_707",
            status=SessionState.ABORTED,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["playback_url"] == vod_url
        assert data["results"]["is_live"] is False

    async def test_get_playback_url_missing_query_param(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should return 422 when post_id query parameter is missing."""
        # Act
        response = await client.get("/flc/session/viewer/get_playback_url")

        # Assert
        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    async def test_get_playback_url_multiple_sessions_same_channel(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should correctly return URL for specific post_id when multiple sessions exist."""
        # Arrange - Create two sessions for same channel with different post_ids
        post_id_1 = "post_multi_1"
        post_id_2 = "post_multi_2"
        live_url_1 = "https://stream.mux.com/multi1.m3u8"
        vod_url_2 = "https://stream.mux.com/multi2.m3u8"

        runtime_1 = SessionRuntime(
            live_playback_url=live_url_1,
            vod_playback_url=None,
            post_id=post_id_1,
        )

        runtime_2 = SessionRuntime(
            live_playback_url="https://stream.mux.com/live2.m3u8",
            vod_playback_url=vod_url_2,
            post_id=post_id_2,
        )

        # First session - LIVE
        session_1 = Session(
            session_id="sess_multi_1",
            room_id="room_multi_1",
            channel_id="ch_multi",
            user_id="user_multi",
            status=SessionState.LIVE,
            runtime=runtime_1,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session_1.create()

        # Second session - STOPPED (older)
        session_2 = Session(
            session_id="sess_multi_2",
            room_id="room_multi_2",
            channel_id="ch_multi",
            user_id="user_multi",
            status=SessionState.STOPPED,
            runtime=runtime_2,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            stopped_at=datetime.now(timezone.utc),
        )
        await session_2.create()

        # Act & Assert - Get first session
        response_1 = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id_1},
        )
        assert response_1.status_code == 200
        data_1 = response_1.json()
        assert data_1["results"]["playback_url"] == live_url_1
        assert data_1["results"]["is_live"] is True

        # Act & Assert - Get second session
        response_2 = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id_2},
        )
        assert response_2.status_code == 200
        data_2 = response_2.json()
        assert data_2["results"]["playback_url"] == vod_url_2
        assert data_2["results"]["is_live"] is False

    async def test_get_playback_url_with_both_urls_live_state(
        self,
        client: AsyncClient,
        beanie_db,
    ):
        """Should prioritize live URL when session is LIVE and both URLs exist."""
        # Arrange
        post_id = "post_both_urls"
        live_url = "https://stream.mux.com/live_both.m3u8"
        vod_url = "https://stream.mux.com/vod_both.m3u8"

        runtime = SessionRuntime(
            live_playback_url=live_url,
            vod_playback_url=vod_url,
            post_id=post_id,
        )

        session = Session(
            session_id="sess_both_urls",
            room_id="room_both_urls",
            channel_id="ch_both",
            user_id="user_both",
            status=SessionState.LIVE,
            runtime=runtime,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.create()

        # Act
        response = await client.get(
            "/flc/session/viewer/get_playback_url",
            params={"post_id": post_id},
        )

        # Assert
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["results"]["playback_url"] == live_url  # Should use live URL
        assert data["results"]["is_live"] is True
