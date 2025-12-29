"""Session viewer endpoints for public/unauthenticated access."""

from fastapi import APIRouter, Query

from app.api.flc.schemas.base import CwOut
from app.api.flc.schemas.session import GetPlaybackUrlOut
from app.schemas import Session, SessionState
from app.utils.flc_errors import FlcError, FlcErrorCode, FlcStatusCode

router = APIRouter(prefix="/flc/session/viewer")


@router.get("/get_playback_url")
async def get_playback_url(
    post_id: str = Query(..., description="Post ID to get playback URL for"),
) -> CwOut[GetPlaybackUrlOut]:
    """Get playback URL for a post.

    During live streaming, returns the live HLS URL.
    After streaming ends, returns the VOD URL.

    Args:
        post_id: Post ID to get playback URL for

    Returns:
        Playback URL and live status

    Raises:
        404: Session not found for post_id
        404: No playback URL available for session
    """
    # Find session by post_id
    session = await Session.find_one(Session.runtime.post_id == post_id)

    if not session:
        raise FlcError(
            errcode=FlcErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found for post_id: {post_id}",
            status_code=FlcStatusCode.NOT_FOUND,
        )

    # Check if session is live
    is_live = session.status in (SessionState.LIVE, SessionState.ENDING)

    # Get appropriate playback URL
    runtime = session.runtime
    if is_live:
        playback_url = runtime.live_playback_url
        if not playback_url:
            raise FlcError(
                errcode=FlcErrorCode.E_NO_LIVE_URL,
                errmesg=f"No live playback URL available for session: {session.session_id}",
                status_code=FlcStatusCode.NOT_FOUND,
            )
    else:
        playback_url = runtime.vod_playback_url
        if not playback_url:
            raise FlcError(
                errcode=FlcErrorCode.E_NO_VOD_URL,
                errmesg=f"No VOD playback URL available for session: {session.session_id}",
                status_code=FlcStatusCode.NOT_FOUND,
            )

    return CwOut[GetPlaybackUrlOut](
        results=GetPlaybackUrlOut(
            playback_url=playback_url,
            is_live=is_live,
        )
    )
