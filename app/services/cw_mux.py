"""Mux helper service.

This module provides a thin wrapper around the `mux-python` package.

Based on the official Mux Python SDK:
https://github.com/muxinc/mux-python

Usage:
    from app.services.cw_mux import mux_service

    # Create a live stream
    live_stream = mux_service.create_live_stream(
        playback_policy="public",
        new_asset_settings=True
    )

    # Delete a live stream
    mux_service.delete_live_stream(stream_id)

    # Signal live stream complete
    mux_service.signal_live_stream_complete(stream_id)
"""

from __future__ import annotations

import mux_python
from loguru import logger
from mux_python.exceptions import NotFoundException as MuxNotFoundException
from pydantic import BaseModel, Field

from app.app_config import get_app_environ_config
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode


class MuxPlaybackId(BaseModel):
    """Mux playback ID model."""

    id: str
    policy: str


class MuxLiveStream(BaseModel):
    """Mux live stream data model."""

    id: str
    stream_key: str
    status: str
    playback_ids: list[MuxPlaybackId] = Field(default_factory=list)
    active_asset_id: str | None = None
    created_at: str | None = None
    passthrough: str | None = None


class MuxLiveStreamResponse(BaseModel):
    """Response model for Mux live stream operations."""

    data: MuxLiveStream


class MuxService:
    """Service wrapper for Mux Video API (mux-python package)."""

    def __init__(self) -> None:
        self._cfg = get_app_environ_config()
        self._demo_mode = bool(getattr(self._cfg, "DEMO_MODE", True))
        self._configuration: mux_python.Configuration | None = None
        self._live_api: mux_python.LiveStreamsApi | None = None
        logger.info("MuxService initialized")

    def _get_configuration(self) -> mux_python.Configuration:
        """Get or create Mux configuration with credentials.

        Returns:
            Mux Configuration instance

        Raises:
            ValueError: If MUX_TOKEN_ID or MUX_TOKEN_SECRET is not configured
        """
        if self._configuration is None:
            if self._demo_mode:
                self._configuration = mux_python.Configuration()
                logger.info("Mux configuration created (DEMO_MODE stub)")
                return self._configuration

            token_id = self._cfg.MUX_TOKEN_ID
            token_secret = self._cfg.MUX_TOKEN_SECRET

            if not token_id or not token_secret:
                logger.error("MUX_TOKEN_ID or MUX_TOKEN_SECRET not configured")
                raise FlcError(
                    errcode=FlcErrorCode.E_INVALID_REQUEST,
                    errmesg="Streaming provider credentials must be configured. Set them in env.local or environment variables.",
                    status_code=FlcStatusCode.BAD_REQUEST,
                )

            self._configuration = mux_python.Configuration()
            self._configuration.username = token_id
            self._configuration.password = token_secret
            logger.info("Mux configuration created")

        return self._configuration

    def _get_live_api(self) -> mux_python.LiveStreamsApi:
        """Get or create LiveStreamsApi client.

        Returns:
            LiveStreamsApi instance
        """
        if self._live_api is None:
            config = self._get_configuration()
            self._live_api = mux_python.LiveStreamsApi(mux_python.ApiClient(config))
            logger.info("Mux LiveStreamsApi client created")
        return self._live_api

    def create_live_stream(
        self,
        playback_policy: str | list[str] = "public",
        new_asset_settings: bool = True,
        reconnect_window: int | None = 60,
        passthrough: str | None = None,
        reduced_latency: bool = False,
        test: bool = False,
        video_quality: str | None = None,
        max_resolution_tier: str | None = "1080p",
        latency_mode: str | None = "standard",
        mp4_support: str | None = "standard",
        master_access: str | None = "temporary",
        normalize_audio: bool = True,
        metadata: dict[str, str] | None = None,
        max_continuous_duration: int | None = 43200,
        static_renditions: list[dict[str, str]] | None = None,
    ) -> MuxLiveStreamResponse:
        """Create a new Mux live stream.

        Args:
            playback_policy: Playback policy ("public" or "signed"), or list of policies
            new_asset_settings: Whether to create an asset from the live stream
            reconnect_window: Time in seconds for reconnection window
            passthrough: Arbitrary metadata to associate with the live stream
            reduced_latency: Enable reduced latency mode (deprecated, use latency_mode)
            test: Create test live stream
            video_quality: Video quality level ("basic", "plus", "premium").
                           Premium provides ~8-12 Mbps for 1080p (industry recommended).
            max_resolution_tier: Maximum resolution tier ("1080p", "1440p", "2160p")
            latency_mode: Latency mode ("standard", "low"). Overrides reduced_latency.
            mp4_support: MP4 support ("none", "standard", "capped-1080p")
            master_access: Master access ("none", "temporary")
            normalize_audio: Whether to normalize audio
            metadata: Optional metadata dict to attach to the asset (e.g., {"video_title": "...", "video_series": "...", "video_id": "..."})
            max_continuous_duration: Maximum duration in seconds for the live stream (default: 43200 = 12 hours)
            static_renditions: List of static rendition configs for the asset (e.g., [{"resolution": "audio-only"}])

        Returns:
            MuxLiveStreamResponse with stream data including:
                - data.id: Unique stream identifier
                - data.stream_key: RTMP stream key
                - data.playback_ids: List of playback IDs for viewing
                - data.status: Stream status (idle, active, disabled)

        Raises:
            ApiException: If API request fails
        """
        if self._demo_mode:
            demo_id = "ls_demo_001"
            demo_stream_key = "sk_demo_redacted"
            demo = MuxLiveStreamResponse(
                data=MuxLiveStream(
                    id=demo_id,
                    stream_key=demo_stream_key,
                    status="idle",
                    playback_ids=[MuxPlaybackId(id="pb_demo_001", policy="public")],
                    active_asset_id=None,
                    created_at=None,
                    passthrough=passthrough,
                )
            )
            logger.info("MuxService DEMO_MODE=true: returning stubbed live stream")
            return demo

        live_api = self._get_live_api()

        # Convert string policy to list
        if isinstance(playback_policy, str):
            policies = [playback_policy.lower()]
        else:
            policies = [p.lower() for p in playback_policy]

        # Build asset settings with video quality parameters
        if new_asset_settings:
            asset_kwargs: dict = {"playback_policy": policies}
            effective_video_quality = (
                video_quality if video_quality is not None else self._cfg.MUX_VIDEO_QUALITY
            )
            asset_kwargs["video_quality"] = effective_video_quality
            if max_resolution_tier is not None:
                asset_kwargs["max_resolution_tier"] = max_resolution_tier
            if mp4_support is not None:
                asset_kwargs["mp4_support"] = mp4_support
            if master_access is not None:
                asset_kwargs["master_access"] = master_access
            asset_kwargs["normalize_audio"] = normalize_audio
            if metadata is not None:
                # Pass metadata dict directly - allows custom keys like video_title, video_series, video_id
                asset_kwargs["metadata"] = metadata
            if static_renditions is not None:
                asset_kwargs["static_renditions"] = static_renditions
            asset_settings = mux_python.CreateAssetRequest(**asset_kwargs)
        else:
            asset_settings = None

        # Build CreateLiveStreamRequest with only non-None values
        kwargs_for_request: dict = {
            "playback_policy": policies,
            "test": test,
        }

        # Handle latency settings
        if latency_mode is not None:
            kwargs_for_request["latency_mode"] = latency_mode
        elif reduced_latency:
            kwargs_for_request["reduced_latency"] = reduced_latency

        if new_asset_settings and asset_settings is not None:
            kwargs_for_request["new_asset_settings"] = asset_settings

        if reconnect_window is not None:
            kwargs_for_request["reconnect_window"] = reconnect_window

        if passthrough is not None:
            kwargs_for_request["passthrough"] = passthrough

        if max_continuous_duration is not None:
            kwargs_for_request["max_continuous_duration"] = max_continuous_duration

        create_request = mux_python.CreateLiveStreamRequest(**kwargs_for_request)  # type: ignore[arg-type]

        effective_quality = (
            video_quality if video_quality is not None else self._cfg.MUX_VIDEO_QUALITY
        )
        logger.info(
            f"Creating Mux live stream with playback_policy={playback_policy}, video_quality={effective_quality}, max_resolution={max_resolution_tier}"
        )

        response = live_api.create_live_stream(create_request)

        # Convert mux_python response to our Pydantic model
        mux_data = response.data  # type: ignore[attr-defined]
        playback_ids = [
            MuxPlaybackId(id=pb.id, policy=pb.policy)  # type: ignore[attr-defined]
            for pb in (mux_data.playback_ids or [])
        ]

        live_stream = MuxLiveStream(
            id=mux_data.id,
            stream_key=mux_data.stream_key,
            status=mux_data.status,
            playback_ids=playback_ids,
            active_asset_id=mux_data.active_asset_id,
            created_at=mux_data.created_at,
            passthrough=mux_data.passthrough,
        )

        result = MuxLiveStreamResponse(data=live_stream)
        logger.info(f"Created Mux live stream with id={result.data.id}")
        return result

    def get_live_stream(self, stream_id: str) -> MuxLiveStreamResponse:
        if self._demo_mode:
            return MuxLiveStreamResponse(
                data=MuxLiveStream(
                    id=stream_id,
                    stream_key="sk_demo_redacted",
                    status="idle",
                    playback_ids=[MuxPlaybackId(id="pb_demo_001", policy="public")],
                    active_asset_id=None,
                )
            )
        """Get a live stream by ID.

        Args:
            stream_id: Unique identifier for the live stream

        Returns:
            MuxLiveStreamResponse with stream data including:
                - data.id: Unique stream identifier
                - data.status: Stream status (idle, active, disabled)
                - data.playback_ids: List of playback IDs for viewing
                - data.active_asset_id: Current active asset ID if streaming

        Raises:
            NotFoundException: If stream not found
            ApiException: If API request fails
        """
        live_api = self._get_live_api()
        logger.info(f"Getting Mux live stream id={stream_id}")
        response = live_api.get_live_stream(stream_id)

        # Convert mux_python response to our Pydantic model
        mux_data = response.data  # type: ignore[attr-defined]
        playback_ids = [
            MuxPlaybackId(id=pb.id, policy=pb.policy)  # type: ignore[attr-defined]
            for pb in (mux_data.playback_ids or [])
        ]

        live_stream = MuxLiveStream(
            id=mux_data.id,
            stream_key=mux_data.stream_key,
            status=mux_data.status,
            playback_ids=playback_ids,
            active_asset_id=mux_data.active_asset_id,
            created_at=mux_data.created_at,
            passthrough=mux_data.passthrough,
        )

        result = MuxLiveStreamResponse(data=live_stream)
        logger.info(f"Got Mux live stream id={stream_id}, status={result.data.status}")
        return result

    def delete_live_stream(self, stream_id: str) -> None:
        """Delete a live stream.

        Args:
            stream_id: Unique identifier for the live stream

        Raises:
            NotFoundException: If stream not found
            ApiException: If API request fails
        """
        if self._demo_mode:
            logger.info("MuxService DEMO_MODE=true: delete_live_stream is a no-op")
            return

        live_api = self._get_live_api()
        logger.info(f"Deleting Mux live stream id={stream_id}")
        live_api.delete_live_stream(stream_id)
        logger.info(f"Deleted Mux live stream id={stream_id}")

    def signal_live_stream_complete(self, stream_id: str) -> None:
        """Signal that a live stream is complete.

        This tells Mux that no more data will be sent to the stream.
        This operation is idempotent - if the stream is not found, it's treated as success.

        Args:
            stream_id: Unique identifier for the live stream

        Raises:
            ApiException: If API request fails (except 404 Not Found)
        """
        if self._demo_mode:
            logger.info("MuxService DEMO_MODE=true: signal_live_stream_complete is a no-op")
            return

        live_api = self._get_live_api()
        logger.info(f"Signaling Mux live stream complete id={stream_id}")
        try:
            live_api.signal_live_stream_complete(stream_id)
            logger.info(f"Signaled Mux live stream complete id={stream_id}")
        except MuxNotFoundException:
            logger.info(f"Mux live stream not found (already deleted/completed) id={stream_id}")

    def get_animated_url(
        self,
        playback_id: str,
        width: int = 640,
        fps: int = 5,
        start: int | None = None,
        end: int | None = None,
    ) -> str:
        """Generate animated GIF URL for a playback ID.

        Args:
            playback_id: Mux playback ID
            width: Width of the animated GIF in pixels (default: 640)
            fps: Frames per second (default: 5)
            start: Start time in milliseconds (optional)
            end: End time in milliseconds (optional)

        Returns:
            URL for animated GIF preview

        Example:
            >>> mux_service.get_animated_url("abc123", 640, 5)
            'https://image.mux.com/abc123/animated.gif?width=640&fps=5'
        """
        base_url = f"{self._cfg.MUX_IMAGE_BASE_URL}/{playback_id}/animated.gif"
        params = [f"width={width}", f"fps={fps}"]

        if start is not None:
            params.append(f"start={start}")
        if end is not None:
            params.append(f"end={end}")

        return f"{base_url}?{'&'.join(params)}"

    def get_thumbnail_url(
        self,
        playback_id: str,
        width: int | None = None,
        height: int | None = None,
        time: float | None = None,
        fit_mode: str = "smartcrop",
    ) -> str:
        """Generate thumbnail URL for a playback ID.

        Args:
            playback_id: Mux playback ID
            width: Width of the thumbnail in pixels (optional)
            height: Height of the thumbnail in pixels (optional)
            time: Time in seconds for the thumbnail (optional)
            fit_mode: Fit mode for the thumbnail (default: "smartcrop")
                Options: "preserve", "stretch", "crop", "smartcrop", "pad"

        Returns:
            URL for thumbnail image

        Example:
            >>> mux_service.get_thumbnail_url("abc123", 853, 480, 60)
            'https://image.mux.com/abc123/thumbnail.jpg?width=853&height=480&fit_mode=smartcrop&time=60'
        """
        base_url = f"{self._cfg.MUX_IMAGE_BASE_URL}/{playback_id}/thumbnail.jpg"
        params = []

        if width is not None:
            params.append(f"width={width}")
        if height is not None:
            params.append(f"height={height}")
        if fit_mode:
            params.append(f"fit_mode={fit_mode}")
        if time is not None:
            params.append(f"time={time}")

        if params:
            return f"{base_url}?{'&'.join(params)}"
        return base_url

    def get_storyboard_url(self, playback_id: str) -> str:
        """Generate storyboard VTT URL for a playback ID.

        The storyboard VTT file contains thumbnail URLs for video scrubbing/preview.

        Args:
            playback_id: Mux playback ID

        Returns:
            URL for storyboard VTT file

        Example:
            >>> mux_service.get_storyboard_url("abc123")
            'https://image.mux.com/abc123/storyboard.vtt'
        """
        return f"{self._cfg.MUX_IMAGE_BASE_URL}/{playback_id}/storyboard.vtt"


# Module-level singleton
mux_service = MuxService()
