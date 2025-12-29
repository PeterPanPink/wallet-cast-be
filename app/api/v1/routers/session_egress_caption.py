"""Caption egress endpoints for retrieving transcripts in various formats."""

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import PlainTextResponse

from app.api.v1.schemas.base import ApiOut
from app.api.v1.schemas.session_egress import GetTranscriptsOut, TranscriptItem
from app.domain.live.session._caption_query import (
    generate_m3u8_playlist_segmented,
    generate_master_m3u8_playlist,
    generate_segment_webvtt,
    generate_webvtt,
    get_session_by_id,
    get_transcripts_for_session,
)
from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

router = APIRouter(prefix="/session/egress/caption", tags=["Next Phase"])


@router.get("/{session_id}/transcripts", response_model=ApiOut[GetTranscriptsOut])
async def get_transcripts(
    session_id: str,
    language: str | None = Query(default=None, description="Filter by language code"),
    start_time: float | None = Query(default=None, description="Filter by start time (seconds)"),
    end_time: float | None = Query(default=None, description="Filter by end time (seconds)"),
) -> ApiOut[GetTranscriptsOut]:
    """Get transcripts for a session in JSON format.

    Args:
        session_id: Session ID to retrieve transcripts for
        language: Optional language filter
        start_time: Optional start time filter (in seconds)
        end_time: Optional end time filter (in seconds)

    Returns:
        List of transcript items with metadata
    """
    # Verify session exists
    session = await get_session_by_id(session_id)
    if not session:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Query transcripts
    transcripts = await get_transcripts_for_session(
        session_id=session_id,
        language=language,
        start_time=start_time,
        end_time=end_time,
    )

    # Convert to response format
    items = [
        TranscriptItem(
            text=t.text,
            language=t.language,
            confidence=t.confidence,
            start_time=t.start_time,
            end_time=t.end_time,
            duration=t.duration,
            speaker_id=t.speaker_id,
            participant_identity=t.participant_identity,
            translations=t.translations,
            created_at=t.created_at.isoformat(),
        )
        for t in transcripts
    ]

    return ApiOut[GetTranscriptsOut](
        results=GetTranscriptsOut(
            session_id=session_id,
            transcripts=items,
            total_count=len(items),
            language_filter=language,
        )
    )


@router.get("/{session_id}/captions.vtt", response_class=PlainTextResponse)
async def get_captions_vtt(
    session_id: str,
    language: str | None = Query(
        default=None,
        description="Language code for translated captions (e.g., 'es', 'fr', 'ja')",
    ),
    start_time: float | None = Query(default=None, description="Filter by start time (seconds)"),
    end_time: float | None = Query(default=None, description="Filter by end time (seconds)"),
) -> Response:
    """Get captions in WebVTT format for a session.

    This endpoint returns captions in WebVTT format, which can be used directly
    with HTML5 video players or HLS streams.

    Args:
        session_id: Session ID to retrieve captions for
        language: Optional language code for translations (if available)
        start_time: Optional start time filter (in seconds)
        end_time: Optional end time filter (in seconds)

    Returns:
        WebVTT formatted captions
    """
    # Verify session exists
    session = await get_session_by_id(session_id)
    if not session:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Query transcripts
    transcripts = await get_transcripts_for_session(
        session_id=session_id,
        language=None,  # Don't filter by language at query level
        start_time=start_time,
        end_time=end_time,
    )

    # Ensure session has started_at timestamp
    if not session.started_at:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_STARTED,
            errmesg=f"Session has not started yet: {session_id}",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

    # Generate WebVTT content with session start time for relative timestamps
    vtt_content = generate_webvtt(transcripts, session.started_at, language=language)

    return PlainTextResponse(
        content=vtt_content,
        media_type="text/vtt",
        headers={
            "Content-Disposition": f'inline; filename="captions_{session_id}.vtt"',
            "Cache-Control": "public, max-age=60",
        },
    )


@router.get("/{session_id}/captions.m3u8", response_class=PlainTextResponse)
async def get_captions_m3u8(
    session_id: str,
    request: Request,
    language: str | None = Query(
        default=None,
        description="Language code for translated captions (e.g., 'es', 'fr', 'ja')",
    ),
) -> Response:
    """Get HLS media playlist with segmented subtitle tracks for a session.

    This endpoint returns an m3u8 media playlist with 4-second VTT segments.
    The playlist maintains the 100 most recent segments based on session start time.

    Args:
        session_id: Session ID to create playlist for
        request: FastAPI request object (for getting base URL)
        language: Optional language code for translated captions

    Returns:
        M3U8 media playlist with VTT segment references
    """
    # Verify session exists
    session = await get_session_by_id(session_id)
    if not session:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Get base URL from request to support ngrok/proxies
    # Check for forwarded protocol (ngrok sets X-Forwarded-Proto)
    proto = request.headers.get("X-Forwarded-Proto", "http")
    host = request.headers.get("Host", str(request.base_url.hostname))
    base_url = f"{proto}://{host}"

    # Generate segmented M3U8 playlist
    m3u8_content = await generate_m3u8_playlist_segmented(
        session_id=session_id,
        base_url=f"{base_url}/api/v1",
        language=language,
    )

    return PlainTextResponse(
        content=m3u8_content,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Content-Disposition": f'inline; filename="captions_{session_id}.m3u8"',
            "Cache-Control": "public, max-age=2",
        },
    )


@router.get("/{session_id}/captions-{segment_num}.vtt", response_class=PlainTextResponse)
async def get_caption_segment(
    session_id: str,
    segment_num: int,
    language: str | None = Query(
        default=None,
        description="Language code for translated captions (e.g., 'es', 'fr', 'ja')",
    ),
) -> Response:
    """Get a specific 4-second VTT caption segment.

    This endpoint returns a single VTT segment containing captions for
    a 4-second time window identified by the segment number.

    Args:
        session_id: Session ID to retrieve captions for
        segment_num: Segment number (media sequence) to retrieve
        language: Optional language code for translations

    Returns:
        WebVTT formatted caption segment
    """
    # Verify session exists
    session = await get_session_by_id(session_id)
    if not session:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Query all transcripts for the session
    transcripts = await get_transcripts_for_session(session_id=session_id)

    # Ensure session has started_at timestamp
    if not session.started_at:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_STARTED,
            errmesg=f"Session has not started yet: {session_id}",
            status_code=HttpStatusCode.BAD_REQUEST,
        )

    # Generate VTT segment with session start time for relative timestamps
    vtt_content = generate_segment_webvtt(
        transcripts=transcripts,
        segment_num=segment_num,
        session_started_at=session.started_at,
        language=language,
    )

    return PlainTextResponse(
        content=vtt_content,
        media_type="text/vtt",
        headers={
            "Content-Disposition": f'inline; filename="captions_{session_id}_{segment_num}.vtt"',
            "Cache-Control": "public, max-age=3600",
        },
    )


@router.get("/{session_id}/master.m3u8", response_class=PlainTextResponse)
async def get_master_playlist(
    session_id: str,
    request: Request,
) -> Response:
    """Get HLS master playlist with video and subtitle tracks.

    This endpoint returns a master M3U8 playlist that combines:
    - The Mux video stream
    - Multiple subtitle tracks (original + translations)

    Users can select their preferred subtitle track in HLS-compatible players.

    Args:
        session_id: Session ID to create master playlist for
        request: FastAPI request object (for getting base URL)

    Returns:
        M3U8 master playlist combining video and subtitles
    """
    # Verify session exists and get Mux playback ID
    session = await get_session_by_id(session_id)
    if not session:
        raise AppError(
            errcode=AppErrorCode.E_SESSION_NOT_FOUND,
            errmesg=f"Session not found: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Extract Mux playback ID from session config
    config = session.runtime
    mux_playback_ids = config.mux.mux_playback_ids if config.mux else None

    if not mux_playback_ids or len(mux_playback_ids) == 0:
        raise AppError(
            errcode=AppErrorCode.E_NO_PLAYBACK_ID,
            errmesg=f"No Mux playback ID found for session: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Get the first public playback ID
    playback_id = None
    for pb in mux_playback_ids:
        pb_dict = pb if isinstance(pb, dict) else pb.model_dump()
        if pb_dict.get("policy") == "public":
            playback_id = pb_dict.get("id")
            break

    if not playback_id:
        raise AppError(
            errcode=AppErrorCode.E_NO_PUBLIC_PLAYBACK_ID,
            errmesg=f"No public Mux playback ID found for session: {session_id}",
            status_code=HttpStatusCode.NOT_FOUND,
        )

    # Get base URL from request to support ngrok/proxies
    # Check for forwarded protocol (ngrok sets X-Forwarded-Proto)
    proto = request.headers.get("X-Forwarded-Proto", "http")
    host = request.headers.get("Host", str(request.base_url.hostname))
    base_url = f"{proto}://{host}"

    # Generate master M3U8 playlist
    m3u8_content = generate_master_m3u8_playlist(
        mux_playback_id=playback_id,
        session_id=session_id,
        base_url=f"{base_url}/api/v1",
    )

    return PlainTextResponse(
        content=m3u8_content,
        media_type="application/vnd.apple.mpegurl",
        headers={
            "Content-Disposition": f'inline; filename="stream_{session_id}.m3u8"',
            "Cache-Control": "public, max-age=2",
        },
    )
