"""Integration tests for Mux service with real Mux API.

These tests are excluded from normal unit tests.
Run with: pytest integration_tests/services/test_mux_integration.py -v

Requires MUX_TOKEN_ID and MUX_TOKEN_SECRET environment variables.
"""

import os
import re

import pytest

from app.services.integrations.external_live.external_live_schemas import ChannelConfig, SessionConfig
from app.services.integrations.mux_service import MuxService


@pytest.mark.integration
class TestMuxServiceIntegration:
    """Integration tests for MuxService with real Mux API."""

    @pytest.fixture
    def mux_credentials(self) -> dict[str, str]:
        """Return Mux credentials from environment variables.

        Raises:
            pytest.skip: If credentials are not provided via environment variables.
        """
        token_id = os.environ.get("MUX_TOKEN_ID")
        token_secret = os.environ.get("MUX_TOKEN_SECRET")

        if not token_id or not token_secret:
            pytest.skip("MUX_TOKEN_ID and MUX_TOKEN_SECRET environment variables required")

        return {
            "MUX_TOKEN_ID": token_id,
            "MUX_TOKEN_SECRET": token_secret,
        }

    @pytest.fixture
    def mux_service(
        self, mux_credentials: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> MuxService:
        """Create MuxService with real credentials."""
        monkeypatch.setenv("MUX_TOKEN_ID", mux_credentials["MUX_TOKEN_ID"])
        monkeypatch.setenv("MUX_TOKEN_SECRET", mux_credentials["MUX_TOKEN_SECRET"])

        # Create a fresh MuxService instance
        service = MuxService()
        # Reset cached config to pick up new env vars
        service._configuration = None
        service._live_api = None
        return service

    def test_create_and_delete_live_stream(self, mux_service: MuxService) -> None:
        """Test creating and deleting a live stream with Mux API.

        This test verifies:
        1. Live stream creation returns valid stream_id, stream_key, playback_ids
        2. The generated URLs match expected Mux URL formats
        3. Live stream can be deleted
        """
        # Create a test live stream
        response = mux_service.create_live_stream(
            playback_policy="public",
            new_asset_settings=True,
            test=True,  # Use test mode to avoid charges
        )

        stream = response.data
        mux_stream_id = stream.id
        mux_stream_key = stream.stream_key

        try:
            # Verify stream was created with required fields
            assert mux_stream_id, "mux_stream_id should not be empty"
            assert mux_stream_key, "mux_stream_key should not be empty"
            assert len(stream.playback_ids) > 0, "Should have at least one playback ID"

            playback_id = stream.playback_ids[0].id
            assert playback_id, "playback_id should not be empty"

            # Build the URLs as we do in production code
            mux_rtmp_url = "rtmps://global-live.mux.com:443/app"
            mux_rtmp_ingest_url = f"{mux_rtmp_url}/{mux_stream_key}"
            live_playback_url = f"https://stream.mux.com/{playback_id}.m3u8"
            animated_url = mux_service.get_animated_url(playback_id, width=640, fps=5)
            thumbnail_url = mux_service.get_thumbnail_url(
                playback_id, width=853, height=480, time=60
            )
            storyboard_url = mux_service.get_storyboard_url(playback_id)

            # Verify URL formats match expected Mux patterns
            assert mux_rtmp_ingest_url.startswith("rtmps://global-live.mux.com:443/app/")
            assert live_playback_url == f"https://stream.mux.com/{playback_id}.m3u8"
            assert (
                animated_url == f"https://image.mux.com/{playback_id}/animated.gif?width=640&fps=5"
            )
            assert (
                thumbnail_url
                == f"https://image.mux.com/{playback_id}/thumbnail.jpg?width=853&height=480&fit_mode=smartcrop&time=60"
            )
            assert storyboard_url == f"https://image.mux.com/{playback_id}/storyboard.vtt"

            # Verify we can construct valid SessionConfig with these values
            session_config = SessionConfig(
                sid="test_session_123",
                url=live_playback_url,
                animatedUrl=animated_url,
                thumbnailUrl=thumbnail_url,
                thumbnails=storyboard_url,
                mux_stream_id=mux_stream_id,
                mux_rtmp_ingest_url=mux_rtmp_ingest_url,
            )

            # Verify serialization produces correct field names
            serialized = session_config.model_dump()
            assert serialized["sid"] == "test_session_123"
            assert serialized["url"] == live_playback_url
            assert serialized["animatedUrl"] == animated_url
            assert serialized["thumbnailUrl"] == thumbnail_url
            assert serialized["thumbnails"] == storyboard_url
            assert serialized["mux_stream_id"] == mux_stream_id
            assert serialized["mux_rtmp_ingest_url"] == mux_rtmp_ingest_url

            # Verify ChannelConfig also works
            channel_config = ChannelConfig(
                channelId="ch_test_123",
                ttl="Test Stream Title",
                img="https://example.com/cover.jpg",
                lang="en",
                categoryIds=["gaming", "tech"],
                location="US",
                dsc="Test description",
            )

            channel_serialized = channel_config.model_dump()
            assert channel_serialized["channelId"] == "ch_test_123"
            assert channel_serialized["ttl"] == "Test Stream Title"
            assert channel_serialized["categoryIds"] == ["gaming", "tech"]

            print("\n✅ Mux Integration Test Results:")
            print(f"  mux_stream_id: {mux_stream_id}")
            print(f"  mux_stream_key: {mux_stream_key[:8]}...")
            print(f"  playback_id: {playback_id}")
            print(f"  mux_rtmp_ingest_url: {mux_rtmp_ingest_url[:50]}...")
            print(f"  live_playback_url: {live_playback_url}")
            print(f"  animated_url: {animated_url}")
            print(f"  thumbnail_url: {thumbnail_url}")
            print(f"  storyboard_url: {storyboard_url}")

        finally:
            # Clean up: delete the test stream
            mux_service.delete_live_stream(mux_stream_id)
            print(f"  ✅ Cleaned up test stream: {mux_stream_id}")

    def test_url_formats_match_example_output(self, mux_service: MuxService) -> None:
        """Test that generated URLs match the expected example output format.

        Example output format:
        {
          "session": {
            "sid": "se_01kc6brrk6700agd1h5fnbyx5t",
            "url": "https://stream.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo.m3u8",
            "animatedUrl": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/animated.gif?width=640&fps=5",
            "thumbnailUrl": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/thumbnail.jpg?width=853&height=480&fit_mode=smartcrop&time=60",
            "thumbnails": "https://image.mux.com/ftxkhkWmTzq8Pr89kz02GQMPUUAMPoZ4rDKDzk3fw02qo/storyboard.vtt",
            "mux_stream_id": "1bgmIA1RuTkB01iohG00iqgB8bQMdZItSkrTZ4014Vfppw",
            "mux_rtmp_ingest_url": "rtmps://global-live.mux.com:443/app/7a9620e3-fab0-cfa0-aa2f-e76c9136267e"
          }
        }
        """
        # Create a test live stream
        response = mux_service.create_live_stream(
            playback_policy="public",
            new_asset_settings=True,
            test=True,
        )

        stream = response.data
        mux_stream_id = stream.id
        mux_stream_key = stream.stream_key
        playback_id = stream.playback_ids[0].id

        try:
            # Build URLs exactly as in production
            mux_rtmp_url = "rtmps://global-live.mux.com:443/app"
            mux_rtmp_ingest_url = f"{mux_rtmp_url}/{mux_stream_key}"
            live_playback_url = f"https://stream.mux.com/{playback_id}.m3u8"
            animated_url = mux_service.get_animated_url(playback_id, width=640, fps=5)
            thumbnail_url = mux_service.get_thumbnail_url(
                playback_id, width=853, height=480, time=60
            )
            storyboard_url = mux_service.get_storyboard_url(playback_id)

            # mux_stream_id: alphanumeric string
            assert re.match(r"^[a-zA-Z0-9]+$", mux_stream_id), (
                f"Invalid mux_stream_id format: {mux_stream_id}"
            )

            # mux_rtmp_ingest_url: rtmps://global-live.mux.com:443/app/{stream_key}
            rtmp_pattern = r"^rtmps://global-live\.mux\.com:443/app/[a-f0-9-]+$"
            assert re.match(rtmp_pattern, mux_rtmp_ingest_url), (
                f"Invalid RTMP URL format: {mux_rtmp_ingest_url}"
            )

            # url: https://stream.mux.com/{playback_id}.m3u8
            hls_pattern = r"^https://stream\.mux\.com/[a-zA-Z0-9]+\.m3u8$"
            assert re.match(hls_pattern, live_playback_url), (
                f"Invalid HLS URL format: {live_playback_url}"
            )

            # animatedUrl: https://image.mux.com/{playback_id}/animated.gif?width=640&fps=5
            animated_pattern = (
                r"^https://image\.mux\.com/[a-zA-Z0-9]+/animated\.gif\?width=640&fps=5$"
            )
            assert re.match(animated_pattern, animated_url), (
                f"Invalid animated URL format: {animated_url}"
            )

            # thumbnailUrl: https://image.mux.com/{playback_id}/thumbnail.jpg?...
            thumbnail_pattern = r"^https://image\.mux\.com/[a-zA-Z0-9]+/thumbnail\.jpg\?width=853&height=480&fit_mode=smartcrop&time=60$"
            assert re.match(thumbnail_pattern, thumbnail_url), (
                f"Invalid thumbnail URL format: {thumbnail_url}"
            )

            # thumbnails (storyboard): https://image.mux.com/{playback_id}/storyboard.vtt
            storyboard_pattern = r"^https://image\.mux\.com/[a-zA-Z0-9]+/storyboard\.vtt$"
            assert re.match(storyboard_pattern, storyboard_url), (
                f"Invalid storyboard URL format: {storyboard_url}"
            )

            print("\n✅ All URL formats match expected patterns")

        finally:
            mux_service.delete_live_stream(mux_stream_id)
