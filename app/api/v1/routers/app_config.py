from fastapi import APIRouter

from app.api.v1.schemas.app_config import FrontendConfigOut
from app.api.v1.schemas.base import ApiOut
from app.app_config import get_app_environ_config

router = APIRouter(prefix="/config")


@router.get("/get_frontend_config")
async def get_frontend_config() -> ApiOut[FrontendConfigOut]:
    """Get frontend configuration.

    Returns URL components for constructing full frontend URLs:
    - Recording URL: {frontend_base_url}{frontend_base_path}{frontend_recording_path}
    - Join/Invite URL: {frontend_invite_link_base_url}{frontend_base_path}{frontend_join_path}

    Example URLs (redacted placeholders for public demo):
    - Recording: https://<redacted-frontend-host>/demo/_recording
    - Invite: https://<redacted-invite-host>/demo/join
    """
    config = get_app_environ_config()

    return ApiOut[FrontendConfigOut](
        results=FrontendConfigOut(
            frontend_base_url=config.FRONTEND_BASE_URL,
            frontend_invite_link_base_url=config.FRONTEND_INVITE_LINK_BASE_URL,
            frontend_base_path=config.FRONTEND_BASE_PATH,
            frontend_recording_path=config.FRONTEND_RECORDING_PATH,
            frontend_join_path=config.FRONTEND_JOIN_PATH,
        )
    )
