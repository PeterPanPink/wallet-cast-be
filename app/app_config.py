from pydantic import BaseModel

from app.api.admin.config import DefaultServiceConfig
from app.shared.config import config, get_dynamic_config

_dynamic_config = None


async def get_app_dynamic_config() -> DefaultServiceConfig:
    """Lazy initialization of dynamic config to avoid Redis connection at import time."""
    global _dynamic_config
    if _dynamic_config is None:
        _dynamic_config = get_dynamic_config()
    await _dynamic_config.reload()

    return DefaultServiceConfig.model_validate(dict(_dynamic_config.items()))  # type: ignore


class AppEnvironConfig(BaseModel):
    # Public demo switch: when enabled, external integrations should use stubs and avoid network calls.
    DEMO_MODE: bool = config.get("DEMO_MODE", "true").strip().lower() == "true"  # type: ignore

    GLOBAL_API_RATE_LIMIT: str = config.get("GLOBAL_API_RATE_LIMIT", "1000/minute").strip()  # type: ignore
    API_CACHE_GLOBAL_EXPIRE_SECONDS: int = int(
        (config.get("API_CACHE_GLOBAL_EXPIRE_SECONDS") or "").strip() or 60
    )
    API_PROBE_BASE_URL: str = config.get("API_PROBE_BASE_URL", "").strip()  # type: ignore
    API_BASE_URL: str = config.get("API_BASE_URL", "http://localhost:8000").strip()  # type: ignore

    # LiveKit configuration
    LIVEKIT_URL: str | None = (config.get("LIVEKIT_URL") or "").strip() or None
    LIVEKIT_API_KEY: str | None = (config.get("LIVEKIT_API_KEY") or "").strip() or None
    LIVEKIT_API_SECRET: str | None = (config.get("LIVEKIT_API_SECRET") or "").strip() or None

    # Mux configuration
    MUX_TOKEN_ID: str | None = (config.get("MUX_TOKEN_ID") or "").strip() or None
    MUX_TOKEN_SECRET: str | None = (config.get("MUX_TOKEN_SECRET") or "").strip() or None
    MUX_WEBHOOK_SIGNING_SECRET: str | None = (
        config.get("MUX_WEBHOOK_SIGNING_SECRET") or ""
    ).strip() or None
    MUX_STREAM_BASE_URL: str = config.get("MUX_STREAM_BASE_URL", "https://<redacted-stream-provider>").strip()  # type: ignore
    MUX_RTMP_INGEST_BASE_URL: str = config.get(
        "MUX_RTMP_INGEST_BASE_URL", "rtmps://<redacted-rtmp-ingest>:443"
    ).strip()  # type: ignore
    MUX_IMAGE_BASE_URL: str = config.get("MUX_IMAGE_BASE_URL", "https://<redacted-image-provider>").strip()  # type: ignore
    MUX_VIDEO_QUALITY: str = config.get("MUX_VIDEO_QUALITY", "premium").strip()  # type: ignore
    # AWS S3 configuration
    AWS_ACCESS_KEY_ID: str | None = (config.get("AWS_ACCESS_KEY_ID") or "").strip() or None
    AWS_SECRET_ACCESS_KEY: str | None = (config.get("AWS_SECRET_ACCESS_KEY") or "").strip() or None
    AWS_REGION: str = config.get("AWS_REGION", "us-east-1").strip()  # type: ignore
    S3_CAPTION_BUCKET: str | None = (config.get("S3_CAPTION_BUCKET") or "").strip() or None
    S3_CAPTION_PREFIX: str = config.get("S3_CAPTION_PREFIX", "captions").strip()  # type: ignore
    # External Live integration (optional)
    EXTERNAL_LIVE_BASE_URL: str | None = (config.get("EXTERNAL_LIVE_BASE_URL") or "").strip() or None
    EXTERNAL_LIVE_API_KEY: str | None = (config.get("EXTERNAL_LIVE_API_KEY") or "").strip() or None
    # Room configuration
    MAX_PARTICIPANTS_LIMIT: int = int((config.get("MAX_PARTICIPANTS_LIMIT") or "").strip() or 20)

    # Egress configuration
    # When True, use web egress with custom recording page; when False, use room composite egress
    USE_WEB_EGRESS: bool = config.get("USE_WEB_EGRESS", "true").strip().lower() == "true"  # type: ignore
    # Video bitrate in kbps for egress streaming (default: 6000)
    LIVEKIT_EGRESS_VIDEO_BITRATE: int = int(
        (config.get("LIVEKIT_EGRESS_VIDEO_BITRATE") or "").strip() or 9600
    )

    # Channel configuration
    DEFAULT_CHANNEL_COVER: str = config.get("DEFAULT_CHANNEL_COVER", "").strip()  # type: ignore

    # Frontend configuration
    FRONTEND_BASE_URL: str | None = config.get("FRONTEND_BASE_URL", "").strip() or None  # type: ignore
    FRONTEND_INVITE_LINK_BASE_URL: str | None = (
        config.get("FRONTEND_INVITE_LINK_BASE_URL", "").strip() or None  # type: ignore
    )  # type: ignore
    FRONTEND_BASE_PATH: str = config.get("FRONTEND_BASE_PATH", "/demo").strip()  # type: ignore
    FRONTEND_RECORDING_PATH: str = config.get("FRONTEND_RECORDING_PATH", "/_recording").strip()  # type: ignore
    FRONTEND_MOBILE_RECORDING_PATH: str = config.get(
        "FRONTEND_MOBILE_RECORDING_PATH", "/_recording-mobile"
    ).strip()  # type: ignore
    FRONTEND_JOIN_PATH: str = config.get("FRONTEND_JOIN_PATH", "/join").strip()  # type: ignore


_app_environ_config = AppEnvironConfig()


def get_app_environ_config() -> AppEnvironConfig:
    return _app_environ_config
