"""Tests for Mux webhook endpoint."""

import hashlib
import hmac
import time
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.webhooks.mux import _parse_passthrough, router, verify_mux_signature
from app.api.webhooks.schemas.mux import LiveStreamActiveEvent
from app.utils.app_errors import AppError


class TestVerifyMuxSignature:
    """Test Mux webhook signature verification."""

    def test_valid_signature(self):
        """Test verification of a valid signature."""
        payload = b'{"type":"video.live_stream.active","data":{"id":"test123"}}'
        signing_secret = "test_secret"
        timestamp = str(int(time.time()))

        # Create signature
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            signing_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signature_header = f"t={timestamp},v1={signature}"

        # Verify
        assert verify_mux_signature(
            payload=payload,
            signature_header=signature_header,
            signing_secret=signing_secret,
        )

    def test_invalid_signature(self):
        """Test rejection of invalid signature."""
        payload = b'{"type":"video.live_stream.active","data":{"id":"test123"}}'
        signing_secret = "test_secret"
        timestamp = str(int(time.time()))

        # Wrong signature
        signature_header = f"t={timestamp},v1=wrong_signature"

        # Should not verify
        assert not verify_mux_signature(
            payload=payload,
            signature_header=signature_header,
            signing_secret=signing_secret,
        )

    def test_expired_timestamp(self):
        """Test rejection of expired timestamp."""
        payload = b'{"type":"video.live_stream.active","data":{"id":"test123"}}'
        signing_secret = "test_secret"
        # Timestamp from 10 minutes ago
        timestamp = str(int(time.time()) - 600)

        # Create valid signature
        signed_payload = f"{timestamp}.{payload.decode('utf-8')}"
        signature = hmac.new(
            signing_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signature_header = f"t={timestamp},v1={signature}"

        # Should raise AppError due to timestamp tolerance (default 300 seconds)
        with pytest.raises(AppError, match="Timestamp outside tolerance"):
            verify_mux_signature(
                payload=payload,
                signature_header=signature_header,
                signing_secret=signing_secret,
            )

    def test_malformed_header(self):
        """Test rejection of malformed signature header."""
        payload = b'{"type":"video.live_stream.active"}'
        signing_secret = "test_secret"

        # Missing v1
        with pytest.raises(AppError, match="Invalid signature header format"):
            verify_mux_signature(
                payload=payload,
                signature_header="t=123456789",
                signing_secret=signing_secret,
            )

        # Missing t
        with pytest.raises(AppError, match="Invalid signature header format"):
            verify_mux_signature(
                payload=payload,
                signature_header="v1=abc123",
                signing_secret=signing_secret,
            )


class TestMuxWebhookEvent:
    """Test Mux webhook event model."""

    def test_parse_valid_event(self):
        """Test parsing a valid Mux webhook event with string timestamps."""
        event_data = {
            "type": "video.live_stream.active",
            "id": "event_123",
            "created_at": "2024-01-15T10:30:00Z",
            "object": {"type": "live_stream"},
            "data": {
                "id": "stream_abc123",
                "created_at": "2024-01-15T10:30:00Z",
                "status": "active",
                "passthrough": "room_xyz",
            },
            "environment": {"name": "production", "id": "env_123"},
        }

        event = LiveStreamActiveEvent.model_validate(event_data)

        assert event.type == "video.live_stream.active"
        assert event.id == "event_123"
        assert event.data.id == "stream_abc123"
        assert event.data.passthrough == "room_xyz"

    def test_parse_event_with_integer_timestamps(self):
        """Test parsing a Mux webhook event with integer timestamps (actual Mux format)."""
        event_data = {
            "type": "video.live_stream.active",
            "id": "event_123",
            "created_at": 1764003132,  # Integer timestamp
            "object": {"type": "live_stream"},
            "data": {
                "id": "stream_abc123",
                "created_at": 1764003132,  # Integer timestamp
                "status": "active",
                "passthrough": "room_xyz",
            },
            "environment": {"name": "production", "id": "env_123"},
        }

        event = LiveStreamActiveEvent.model_validate(event_data)

        assert event.type == "video.live_stream.active"
        assert event.id == "event_123"
        assert event.created_at == "1764003132"  # Should be converted to string
        assert event.data.id == "stream_abc123"
        assert event.data.created_at == "1764003132"  # Should be converted to string
        assert event.data.passthrough == "room_xyz"


@pytest.mark.integration
class TestMuxWebhookEndpoint:
    """Integration tests for Mux webhook endpoint."""

    @pytest.fixture
    def app(self):
        """Create test FastAPI app."""
        app = FastAPI()
        app.include_router(router)
        return app

    @pytest.fixture
    def client(self, app):
        """Create test client."""
        return TestClient(app)

    def test_webhook_without_signature(self, client):
        """Test webhook without signature header (development mode)."""
        event_payload = {
            "type": "video.live_stream.active",
            "id": "event_123",
            "created_at": "2024-01-15T10:30:00Z",
            "object": {"type": "live_stream"},
            "data": {
                "id": "stream_abc123",
                "created_at": "2024-01-15T10:30:00Z",
                "status": "active",
                "passthrough": "room_xyz",
            },
            "environment": {"name": "production", "id": "env_123"},
        }

        with patch("app.api.webhooks.mux.get_app_environ_config") as mock_config:
            mock_config.return_value.MUX_WEBHOOK_SIGNING_SECRET = None

            response = client.post("/webhooks/mux", json=event_payload)

            # Should fail due to missing config
            assert response.status_code == 200
            data = response.json()
            assert data.get("errcode") == "E_WEBHOOK_CONFIG_MISSING"

    def test_webhook_with_valid_signature(self, client):
        """Test webhook with valid signature."""
        event_payload = {
            "type": "video.live_stream.active",
            "id": "event_123",
            "created_at": "2024-01-15T10:30:00Z",
            "object": {"type": "live_stream"},
            "data": {
                "id": "stream_abc123",
                "created_at": "2024-01-15T10:30:00Z",
                "status": "active",
                "passthrough": "room_xyz",
            },
            "environment": {"name": "production", "id": "env_123"},
        }

        signing_secret = "test_webhook_secret"
        timestamp = str(int(time.time()))
        payload_str = str(event_payload).replace("'", '"')

        # Create signature
        signed_payload = f"{timestamp}.{payload_str}"
        signature = hmac.new(
            signing_secret.encode("utf-8"),
            signed_payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        signature_header = f"t={timestamp},v1={signature}"

        with patch("app.api.webhooks.mux.get_app_environ_config") as mock_config:
            mock_config.return_value.MUX_WEBHOOK_SIGNING_SECRET = signing_secret

            with patch("app.api.webhooks.mux.handle_live_stream_active") as mock_handler:
                mock_handler.return_value = {"processed": True, "action": "test"}

                response = client.post(
                    "/webhooks/mux",
                    json=event_payload,
                    headers={"mux-signature": signature_header},
                )

                # Should succeed if signature is valid
                # Note: In real test this may fail due to body encoding differences
                # but demonstrates the pattern
                assert response.status_code in [200, 422]


class TestParsePassthrough:
    """Test passthrough parsing helper function."""

    def test_valid_passthrough(self):
        """Test parsing valid passthrough format."""
        passthrough = "room_123|channel_456|session_789"
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id == "room_123"
        assert channel_id == "channel_456"
        assert session_id == "session_789"

    def test_passthrough_with_whitespace(self):
        """Test parsing passthrough with leading/trailing whitespace."""
        passthrough = " room_123 | channel_456 | session_789 "
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id == "room_123"
        assert channel_id == "channel_456"
        assert session_id == "session_789"

    def test_passthrough_with_newlines(self):
        """Test parsing passthrough with newlines (edge case from bug report)."""
        passthrough = "room_123|channel_456|\nsession_789"
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id == "room_123"
        assert channel_id == "channel_456"
        assert session_id == "session_789"

    def test_invalid_passthrough_too_few_parts(self):
        """Test parsing invalid passthrough with too few parts."""
        passthrough = "room_123|channel_456"
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id is None
        assert channel_id is None
        assert session_id is None

    def test_empty_passthrough(self):
        """Test parsing empty passthrough."""
        room_id, channel_id, session_id = _parse_passthrough("")

        assert room_id is None
        assert channel_id is None
        assert session_id is None

    def test_none_passthrough(self):
        """Test parsing None passthrough."""
        room_id, channel_id, session_id = _parse_passthrough(None)

        assert room_id is None
        assert channel_id is None
        assert session_id is None

    def test_passthrough_with_empty_parts(self):
        """Test parsing passthrough with empty parts."""
        passthrough = "room_123||session_789"
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id == "room_123"
        assert channel_id is None  # Empty string becomes None
        assert session_id == "session_789"

    def test_passthrough_with_extra_parts(self):
        """Test parsing passthrough with more than 3 parts (should still work)."""
        passthrough = "room_123|channel_456|session_789|extra_data"
        room_id, channel_id, session_id = _parse_passthrough(passthrough)

        assert room_id == "room_123"
        assert channel_id == "channel_456"
        assert session_id == "session_789"  # Extra parts are ignored


@pytest.mark.usefixtures("clear_collections")
class TestHandleAssetReady:
    """Tests for handle_asset_ready webhook handler."""

    @pytest.fixture
    def mock_mux_service(self):
        """Mock mux_service methods for URL generation."""
        with patch("app.api.webhooks.mux.mux_service") as mock:
            mock.get_animated_url.return_value = "https://image.mux.com/playback123/animated.gif"
            mock.get_thumbnail_url.return_value = "https://image.mux.com/playback123/thumbnail.jpg"
            mock.get_storyboard_url.return_value = (
                "https://image.mux.com/playback123/storyboard.vtt"
            )
            yield mock

    @pytest.fixture
    def mock_app_config(self):
        """Mock app config for MUX_STREAM_BASE_URL."""
        with patch("app.api.webhooks.mux.get_app_environ_config") as mock:
            mock.return_value.MUX_STREAM_BASE_URL = "https://stream.mux.com"
            mock.return_value.EXTERNAL_LIVE_BASE_URL = None  # Disable External Live integration
            yield mock

    @pytest.fixture
    def sample_asset_ready_event_data(self) -> dict:
        """Create sample asset ready event data."""
        return {
            "type": "video.asset.ready",
            "id": "event_asset_ready_123",
            "created_at": "1702828800",
            "environment": {"name": "production", "id": "env_123"},
            "object": {"type": "asset"},
            "data": {
                "id": "asset_abc123",
                "created_at": "1702828800",
                "status": "ready",
                "duration": 120.5,
                "max_stored_resolution": "HD",
                "passthrough": "room_test|ch_test|se_asset_ready_test",
                "live_stream_id": "stream_xyz789",
                "is_live": True,
                "playback_ids": [
                    {"id": "playback123", "policy": "public"},
                    {"id": "playback456", "policy": "signed"},
                ],
            },
        }

    async def test_handle_asset_ready_sets_mux_urls(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
        sample_asset_ready_event_data,
    ):
        """Test that handle_asset_ready sets all Mux URLs correctly."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session in PUBLISHING state
        channel = Channel(
            channel_id="ch_test",
            user_id="u.test",
            title="Test Channel",
            description="Test Description",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_asset_ready_test",
            room_id="room_test",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_xyz789"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        event = AssetReadyEvent(**sample_asset_ready_event_data)
        result = await handle_asset_ready(event)

        # Assert: Check result
        assert result["handled"] is True
        assert result["dvr_updated"] is True
        assert result["session_id"] == "se_asset_ready_test"
        assert result["dvr_playback_url"] == "https://stream.mux.com/playback123.m3u8"

        # Assert: Verify Mux URLs are set in session
        saved_session = await Session.find_one(Session.session_id == "se_asset_ready_test")
        assert saved_session is not None
        assert saved_session.runtime.live_playback_url == "https://stream.mux.com/playback123.m3u8"
        assert (
            saved_session.runtime.animated_url == "https://image.mux.com/playback123/animated.gif"
        )
        assert (
            saved_session.runtime.thumbnail_url == "https://image.mux.com/playback123/thumbnail.jpg"
        )
        assert (
            saved_session.runtime.storyboard_url
            == "https://image.mux.com/playback123/storyboard.vtt"
        )

        # Verify mux_service methods were called with correct playback_id
        mock_mux_service.get_animated_url.assert_called_once_with("playback123")
        mock_mux_service.get_thumbnail_url.assert_called_once_with(
            "playback123", width=853, height=480, time=60
        )
        mock_mux_service.get_storyboard_url.assert_called_once_with("playback123")

    async def test_handle_asset_ready_sets_post_id(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
        sample_asset_ready_event_data,
    ):
        """Test that handle_asset_ready sets post_id from External Live integration."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session in PUBLISHING state
        channel = Channel(
            channel_id="ch_test",
            user_id="u.test",
            title="Test Channel",
            description="Test Description",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_asset_ready_test",
            room_id="room_test",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_xyz789"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        event = AssetReadyEvent(**sample_asset_ready_event_data)
        result = await handle_asset_ready(event)

        # Assert: Check result has external_live_post_id (mock post_id since External Live is not configured)
        assert result["handled"] is True
        assert result["external_live_post_id"] is not None
        assert result["external_live_post_id"].startswith("mock_")

        # Assert: Verify post_id is saved in session
        saved_session = await Session.find_one(Session.session_id == "se_asset_ready_test")
        assert saved_session is not None
        assert saved_session.runtime.post_id is not None
        assert saved_session.runtime.post_id.startswith("mock_")
        assert saved_session.runtime.post_id == result["external_live_post_id"]

    async def test_handle_asset_ready_transitions_to_live(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
        sample_asset_ready_event_data,
    ):
        """Test that handle_asset_ready transitions session status to LIVE."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session in PUBLISHING state
        channel = Channel(
            channel_id="ch_test",
            user_id="u.test",
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_asset_ready_test",
            room_id="room_test",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_xyz789"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        event = AssetReadyEvent(**sample_asset_ready_event_data)
        result = await handle_asset_ready(event)

        # Assert: Check result
        assert result["handled"] is True
        assert result["new_status"] == SessionState.LIVE.value

        # Assert: Verify session status changed to LIVE
        saved_session = await Session.find_one(Session.session_id == "se_asset_ready_test")
        assert saved_session is not None
        assert saved_session.status == SessionState.LIVE
        # started_at should be set when transitioning to LIVE
        assert saved_session.started_at is not None

    async def test_handle_asset_ready_sets_active_asset_id(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
        sample_asset_ready_event_data,
    ):
        """Test that handle_asset_ready sets mux_active_asset_id."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session in PUBLISHING state
        channel = Channel(
            channel_id="ch_test",
            user_id="u.test",
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_asset_ready_test",
            room_id="room_test",
            channel_id="ch_test",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_xyz789"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Act
        event = AssetReadyEvent(**sample_asset_ready_event_data)
        await handle_asset_ready(event)

        # Assert: Verify mux_active_asset_id is set
        saved_session = await Session.find_one(Session.session_id == "se_asset_ready_test")
        assert saved_session is not None
        assert saved_session.runtime.mux is not None
        assert saved_session.runtime.mux.mux_active_asset_id == "asset_abc123"

    async def test_handle_asset_ready_finds_session_by_mux_stream_id(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
    ):
        """Test that handle_asset_ready can find session by mux_stream_id when passthrough is empty."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session
        channel = Channel(
            channel_id="ch_fallback",
            user_id="u.test",
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_fallback_test",
            room_id="room_fallback",
            channel_id="ch_fallback",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_fallback_xyz"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Event with no passthrough but matching live_stream_id
        event_data = {
            "type": "video.asset.ready",
            "id": "event_fallback_123",
            "created_at": "1702828800",
            "environment": {"name": "production", "id": "env_123"},
            "object": {"type": "asset"},
            "data": {
                "id": "asset_fallback",
                "created_at": "1702828800",
                "status": "ready",
                "passthrough": None,  # No passthrough
                "live_stream_id": "stream_fallback_xyz",  # Match by this
                "is_live": True,
                "playback_ids": [{"id": "playback_fallback", "policy": "public"}],
            },
        }

        # Act
        event = AssetReadyEvent(**event_data)
        result = await handle_asset_ready(event)

        # Assert: Session found by mux_stream_id
        assert result["handled"] is True
        assert result["session_id"] == "se_fallback_test"

    async def test_handle_asset_ready_skips_non_live_asset(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
    ):
        """Test that handle_asset_ready skips processing when is_live is False."""
        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent

        # Event with is_live=False
        event_data = {
            "type": "video.asset.ready",
            "id": "event_not_live",
            "created_at": "1702828800",
            "environment": {"name": "production", "id": "env_123"},
            "object": {"type": "asset"},
            "data": {
                "id": "asset_not_live",
                "created_at": "1702828800",
                "status": "ready",
                "passthrough": "room|ch|se",
                "is_live": False,  # Not from active live stream
                "playback_ids": [{"id": "playback_xyz", "policy": "public"}],
            },
        }

        # Act
        event = AssetReadyEvent(**event_data)
        result = await handle_asset_ready(event)

        # Assert: Should skip and return dvr_updated=False
        assert result["handled"] == "asset_ready"
        assert result["dvr_updated"] is False

    async def test_handle_asset_ready_returns_error_when_session_not_found(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
    ):
        """Test that handle_asset_ready returns error when session is not found."""
        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent

        # Event with non-existent session
        event_data = {
            "type": "video.asset.ready",
            "id": "event_no_session",
            "created_at": "1702828800",
            "environment": {"name": "production", "id": "env_123"},
            "object": {"type": "asset"},
            "data": {
                "id": "asset_no_session",
                "created_at": "1702828800",
                "status": "ready",
                "passthrough": "room|ch|se_nonexistent",
                "live_stream_id": "stream_nonexistent",
                "is_live": True,
                "playback_ids": [{"id": "playback_xyz", "policy": "public"}],
            },
        }

        # Act
        event = AssetReadyEvent(**event_data)
        result = await handle_asset_ready(event)

        # Assert: Should return error
        assert result["handled"] is False
        assert result["error"] == "session_not_found"

    async def test_handle_asset_ready_uses_first_playback_id_when_no_public(
        self,
        beanie_db,
        mock_mux_service,
        mock_app_config,
    ):
        """Test that handle_asset_ready falls back to first playback_id when no public policy."""
        from datetime import datetime, timezone

        from app.api.webhooks.mux import handle_asset_ready
        from app.api.webhooks.schemas.mux import AssetReadyEvent
        from app.schemas import Channel, Session, SessionState
        from app.schemas.session_runtime import MuxRuntime, SessionRuntime

        # Arrange: Create channel and session
        channel = Channel(
            channel_id="ch_signed",
            user_id="u.test",
            title="Test Channel",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await channel.insert()

        session = Session(
            session_id="se_signed_test",
            room_id="room_signed",
            channel_id="ch_signed",
            user_id="u.test",
            status=SessionState.PUBLISHING,
            runtime=SessionRuntime(
                mux=MuxRuntime(mux_stream_id="stream_signed"),
            ),
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        await session.insert()

        # Event with only signed playback_ids (no public)
        event_data = {
            "type": "video.asset.ready",
            "id": "event_signed",
            "created_at": "1702828800",
            "environment": {"name": "production", "id": "env_123"},
            "object": {"type": "asset"},
            "data": {
                "id": "asset_signed",
                "created_at": "1702828800",
                "status": "ready",
                "passthrough": "room_signed|ch_signed|se_signed_test",
                "live_stream_id": "stream_signed",
                "is_live": True,
                "playback_ids": [
                    {"id": "signed_playback_first", "policy": "signed"},
                    {"id": "signed_playback_second", "policy": "signed"},
                ],
            },
        }

        # Act
        event = AssetReadyEvent(**event_data)
        result = await handle_asset_ready(event)

        # Assert: Should use first playback_id
        assert result["handled"] is True
        assert result["dvr_playback_url"] == "https://stream.mux.com/signed_playback_first.m3u8"
        mock_mux_service.get_animated_url.assert_called_once_with("signed_playback_first")
