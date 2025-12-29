"""Domain logic for querying and formatting caption transcripts."""

from collections.abc import Sequence
from datetime import datetime, timezone

from app.app_config import get_app_environ_config
from app.schemas import Session, Transcript

# Segment duration in seconds
SEGMENT_DURATION = 4.0
# Maximum number of segments to keep in playlist
MAX_SEGMENTS = 100


def _utc_timestamp(dt: datetime) -> float:
    """Convert a datetime to a UTC Unix timestamp.

    MongoDB datetimes are commonly stored/returned as tz-naive but represent UTC. Treat
    tz-naive datetimes as UTC to avoid timezone-dependent offsets in caption timing.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


async def get_transcripts_for_session(
    session_id: str,
    language: str | None = None,
    start_time: float | None = None,
    end_time: float | None = None,
) -> list[Transcript]:
    """Query transcripts for a session with optional filters.

    Args:
        session_id: Session ID to query transcripts for
        language: Optional language filter
        start_time: Optional start time filter (in seconds)
        end_time: Optional end time filter (in seconds)

    Returns:
        List of Transcript documents ordered by start_time
    """
    query = Transcript.find(Transcript.session_id == session_id)

    if language:
        query = query.find(Transcript.language == language)

    if start_time is not None:
        query = query.find(Transcript.start_time >= start_time)

    if end_time is not None:
        query = query.find(Transcript.end_time <= end_time)

    transcripts = await query.sort("start_time").to_list()
    return transcripts


def format_time_vtt(seconds: float) -> str:
    """Format time in WebVTT format (HH:MM:SS.mmm).

    Args:
        seconds: Time in seconds

    Returns:
        Formatted time string
    """
    total_ms = round(seconds * 1000)
    hours, rem = divmod(total_ms, 3600 * 1000)
    minutes, rem = divmod(rem, 60 * 1000)
    secs, millis = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}.{millis:03d}"


def calculate_segment_number(time_seconds: float, started_at: datetime) -> int:
    """Calculate segment number based on time since session start.

    Args:
        time_seconds: Absolute Unix timestamp (UTC) from the transcript
        started_at: Session start datetime (UTC)

    Returns:
        Segment number (media sequence)
    """
    # Convert session start datetime to Unix timestamp (UTC)
    session_start_ts = _utc_timestamp(started_at)
    # Calculate relative offset from session start
    relative_time = time_seconds - session_start_ts
    return max(0, int(relative_time // SEGMENT_DURATION))


def get_segment_time_range(segment_num: int) -> tuple[float, float]:
    """Get time range for a specific segment.

    Args:
        segment_num: Segment number (media sequence)

    Returns:
        Tuple of (start_time, end_time) in seconds
    """
    start_time = segment_num * SEGMENT_DURATION
    end_time = start_time + SEGMENT_DURATION
    return start_time, end_time


def generate_segment_webvtt(
    transcripts: Sequence[Transcript],
    segment_num: int,
    session_started_at: datetime,
    language: str | None = None,
) -> str:
    """Generate WebVTT format for a specific segment.

    Args:
        transcripts: List of Transcript documents (with absolute UTC timestamps)
        segment_num: Segment number to generate
        session_started_at: Session start datetime (UTC) for converting to relative time
        language: Optional language code for translation lookup

    Returns:
        WebVTT formatted string for the segment
    """
    start_time, end_time = get_segment_time_range(segment_num)
    session_start_ts = _utc_timestamp(session_started_at)

    # Filter transcripts that overlap with this segment (using relative time)
    segment_transcripts = [
        t
        for t in transcripts
        if (t.start_time - session_start_ts) < end_time
        and (t.end_time - session_start_ts) > start_time
    ]

    lines = ["WEBVTT", ""]

    for idx, transcript in enumerate(segment_transcripts, 1):
        # Use translation if language specified and available
        text = transcript.text
        if language and transcript.translations and language in transcript.translations:
            text = transcript.translations[language]

        # Convert absolute timestamps to relative time (seconds from session start)
        relative_start = transcript.start_time - session_start_ts
        relative_end = transcript.end_time - session_start_ts

        # Clamp times to segment boundaries
        t_start = max(relative_start, start_time)
        t_end = min(relative_end, end_time)

        start = format_time_vtt(t_start)
        end = format_time_vtt(t_end)

        lines.append(f"{idx}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def generate_webvtt(
    transcripts: list[Transcript],
    session_started_at: datetime,
    language: str | None = None,
) -> str:
    """Generate WebVTT format caption file from transcripts.

    Args:
        transcripts: List of Transcript documents (with absolute UTC timestamps)
        session_started_at: Session start datetime (UTC) for converting to relative time
        language: Optional language code for translation lookup

    Returns:
        WebVTT formatted string with times relative to session start
    """
    lines = ["WEBVTT", ""]
    session_start_ts = _utc_timestamp(session_started_at)

    for idx, transcript in enumerate(transcripts, 1):
        # Use translation if language specified and available
        text = transcript.text
        if language and transcript.translations and language in transcript.translations:
            text = transcript.translations[language]

        # Convert absolute timestamps to relative time (seconds from session start)
        relative_start = transcript.start_time - session_start_ts
        relative_end = transcript.end_time - session_start_ts

        start = format_time_vtt(relative_start)
        end = format_time_vtt(relative_end)

        lines.append(f"{idx}")
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    return "\n".join(lines)


def generate_m3u8_playlist(
    session_id: str,
    base_url: str,
    languages: list[str] | None = None,
) -> str:
    """Generate HLS m3u8 playlist with subtitle tracks.

    Args:
        session_id: Session ID
        base_url: Base URL for the API endpoints
        languages: List of language codes for subtitle tracks

    Returns:
        M3U8 playlist content
    """
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", ""]

    # Add default subtitle track (original language)
    lines.extend(
        [
            '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="Original",'
            "DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,"
            f'URI="{base_url}/session/egress/caption/{session_id}/captions.vtt"',
            "",
        ]
    )

    # Add translated subtitle tracks if languages specified
    if languages:
        for lang in languages:
            lang_name = lang.capitalize()
            lines.extend(
                [
                    f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="{lang_name}",'
                    "DEFAULT=NO,AUTOSELECT=NO,FORCED=NO,"
                    f'URI="{base_url}/session/egress/caption/{session_id}/captions.vtt?language={lang}"',
                    "",
                ]
            )

    return "\n".join(lines)


def generate_master_m3u8_playlist(
    mux_playback_id: str,
    session_id: str,
    base_url: str,
) -> str:
    """Generate HLS master m3u8 playlist with video and subtitle tracks.

    This creates a master playlist that references:
    - The Mux video stream
    - Multiple subtitle tracks (original + translations)

    Args:
        mux_playback_id: Mux playback ID for the video stream
        session_id: Session ID for subtitle tracks
        base_url: Base URL for the API endpoints

    Returns:
        Master M3U8 playlist content
    """
    # Language name mapping for better display
    language_names = {
        "es": "Spanish",
        "fr": "French",
        "de": "German",
        "it": "Italian",
        "pt": "Portuguese",
        "ja": "Japanese",
        "ko": "Korean",
        "zh": "Chinese",
        "ar": "Arabic",
        "hi": "Hindi",
    }

    languages = list(language_names.keys())

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "",
    ]

    # Add subtitle tracks
    # Original language (English assumed)
    lines.append(
        '#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="English",'
        'LANGUAGE="en",DEFAULT=YES,AUTOSELECT=YES,FORCED=NO,'
        f'URI="{base_url}/session/egress/caption/{session_id}/captions.m3u8"'
    )

    # Add translated subtitle tracks
    for lang_code in languages:
        lang_name = language_names[lang_code]
        lines.append(
            f'#EXT-X-MEDIA:TYPE=SUBTITLES,GROUP-ID="subs",NAME="{lang_name}",'
            f'LANGUAGE="{lang_code}",DEFAULT=NO,AUTOSELECT=NO,FORCED=NO,'
            f'URI="{base_url}/session/egress/caption/{session_id}/captions.m3u8?language={lang_code}"'
        )

    lines.append("")

    # Add video stream variant with subtitle group
    config = get_app_environ_config()
    mux_stream_base_url = config.MUX_STREAM_BASE_URL
    lines.extend(
        [
            '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080,SUBTITLES="subs"',
            f"{mux_stream_base_url}/{mux_playback_id}.m3u8",
        ]
    )

    return "\n".join(lines)


async def generate_m3u8_playlist_segmented(
    session_id: str,
    base_url: str,
    language: str | None = None,
) -> str:
    """Generate HLS m3u8 media playlist with segmented subtitle tracks.

    Args:
        session_id: Session ID
        base_url: Base URL for the API endpoints
        language: Optional language code for translated captions

    Returns:
        M3U8 media playlist content with segments
    """
    # Get session to determine started_at and calculate segments
    session = await get_session_by_id(session_id)
    if not session or not session.started_at:
        # Return empty playlist if session hasn't started
        return "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n"

    # Get all transcripts to determine latest segments
    transcripts = await get_transcripts_for_session(session_id=session_id)

    if not transcripts:
        # No transcripts yet
        return "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:4\n#EXT-X-MEDIA-SEQUENCE:0\n"

    # Find max segment number from latest transcript
    max_time = max(t.end_time for t in transcripts)
    latest_segment = calculate_segment_number(max_time, session.started_at)

    # Calculate media sequence (oldest segment to keep)
    media_sequence = max(0, latest_segment - MAX_SEGMENTS + 1)

    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        "#EXT-X-TARGETDURATION:4",
        f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
        "",
    ]

    # Add segments
    lang_param = f"?language={language}" if language else ""
    for seg_num in range(media_sequence, latest_segment + 1):
        lines.append("#EXTINF:4.0,")
        lines.append(
            f"{base_url}/session/egress/caption/{session_id}/captions-{seg_num}.vtt{lang_param}"
        )

    return "\n".join(lines)


async def get_session_by_id(session_id: str) -> Session | None:
    """Get session by ID.

    Args:
        session_id: Session ID to look up

    Returns:
        Session document or None if not found
    """
    return await Session.find_one(Session.session_id == session_id)
