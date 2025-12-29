"""S3 caption uploader for LiveKit sessions.

This module handles periodic upload of caption segments to S3 for HLS delivery.
"""

import asyncio
import math
from datetime import datetime

from loguru import logger

from app.shared.storage.redis import get_redis_client
from app.domain.live.session._caption_query import (
    MAX_SEGMENTS,
    SEGMENT_DURATION,
    calculate_segment_number,
    generate_segment_webvtt,
    get_transcripts_for_session,
)
from app.schemas import Session, Transcript
from app.services.integrations.s3_storage import s3_service


class CaptionS3Uploader:
    """Handles periodic upload of caption segments to S3."""

    DEFAULT_UPLOAD_INTERVAL = 5.0  # seconds between upload checks
    PLAYLIST_CACHE_CONTROL = "public, max-age=2"
    SEGMENT_CACHE_CONTROL = "public, max-age=31536000, immutable"

    def __init__(
        self,
        redis_label: str,
        upload_interval: float = DEFAULT_UPLOAD_INTERVAL,
    ) -> None:
        """Initialize the S3 uploader.

        Args:
            redis_label: Redis connection label for querying active agents
            upload_interval: Seconds between upload checks
        """
        self._redis_label = redis_label
        self._upload_interval = upload_interval
        self._running = False

    async def run(self) -> None:
        """Run the upload loop continuously."""
        logger.info("Starting S3 caption upload background task")
        self._running = True

        while self._running:
            try:
                await asyncio.sleep(self._upload_interval)
                await self._process_active_sessions()
            except Exception as exc:
                logger.exception(f"Error in S3 upload task: {exc}")
                await asyncio.sleep(5)

    def stop(self) -> None:
        """Signal the upload loop to stop."""
        self._running = False

    async def _process_active_sessions(self) -> None:
        """Process all active sessions with caption agents."""
        redis = get_redis_client(self._redis_label)

        agent_keys = []
        async for key in redis.scan_iter(match="caption-agent:*"):
            agent_keys.append(key)

        if not agent_keys:
            return

        for agent_key in agent_keys:
            await self._process_session(redis, agent_key)

    async def _process_session(self, redis, agent_key: bytes) -> None:
        """Process a single session for caption upload."""
        session_id = None
        try:
            agent_data = await redis.hgetall(agent_key)
            if not agent_data or agent_data.get(b"status") != b"running":
                return

            session_id_bytes = agent_data.get(b"session_id")
            if not session_id_bytes:
                return

            session_id = session_id_bytes.decode("utf-8")
            session = await Session.find_one(Session.session_id == session_id)
            if not session or not session.started_at:
                return

            transcripts = await get_transcripts_for_session(session_id=session_id)
            if not transcripts:
                return

            await self._upload_session_captions(session, transcripts)

        except Exception as exc:
            logger.exception(f"Failed to upload captions for session {session_id}: {exc}")

    async def _upload_session_captions(
        self,
        session: Session,
        transcripts: list[Transcript],
    ) -> None:
        """Upload caption segments and playlists for a session."""
        # started_at is guaranteed non-None by _process_session check
        assert session.started_at is not None

        max_time = max(t.end_time for t in transcripts)
        latest_segment = calculate_segment_number(max_time, session.started_at)

        last_uploaded = session.caption_last_uploaded_segment or -1
        new_segments = list(range(last_uploaded + 1, latest_segment + 1))

        if not new_segments:
            return

        logger.info(
            f"Uploading {len(new_segments)} caption segments for session {session.session_id}"
        )

        languages = self._get_available_languages(transcripts)
        files_to_upload = self._prepare_files_for_upload(
            started_at=session.started_at,
            transcripts=transcripts,
            new_segments=new_segments,
            latest_segment=latest_segment,
            languages=languages,
        )

        # Upload segments first, then playlists so the playlist doesn't reference missing objects.
        vtt_files = [item for item in files_to_upload if item[0].endswith(".vtt")]
        m3u8_files = [item for item in files_to_upload if item[0].endswith(".m3u8")]

        uploaded_urls: dict[str, str] = {}
        if vtt_files:
            uploaded_urls.update(
                await s3_service.upload_caption_files_batch(
                    session_id=session.session_id,
                    files=vtt_files,
                    cache_control=self.SEGMENT_CACHE_CONTROL,
                )
            )
        if m3u8_files:
            uploaded_urls.update(
                await s3_service.upload_caption_files_batch(
                    session_id=session.session_id,
                    files=m3u8_files,
                    cache_control=self.PLAYLIST_CACHE_CONTROL,
                )
            )

        session.caption_last_uploaded_segment = latest_segment
        if not session.caption_s3_urls:
            session.caption_s3_urls = {}
        session.caption_s3_urls.update(uploaded_urls)

        await session.partial_update_session_with_version_check(
            {
                Session.caption_last_uploaded_segment: session.caption_last_uploaded_segment,
                Session.caption_s3_urls: session.caption_s3_urls,
            },
            max_retry_on_conflicts=2,
        )

        logger.info(
            f"✅ Uploaded {len(files_to_upload)} caption files for session {session.session_id}"
        )

    def _get_available_languages(self, transcripts: list[Transcript]) -> set[str]:
        """Get all available translation languages from transcripts."""
        languages = set()
        for t in transcripts:
            if t.translations:
                languages.update(t.translations.keys())
        return languages

    def _prepare_files_for_upload(
        self,
        started_at: datetime,
        transcripts: list[Transcript],
        new_segments: list[int],
        latest_segment: int,
        languages: set[str],
    ) -> list[tuple[str, str, str]]:
        """Prepare all files for batch upload."""
        files: list[tuple[str, str, str]] = []

        # Add VTT segments
        files.extend(self._generate_vtt_segments(started_at, transcripts, new_segments, languages))

        # Add M3U8 playlists
        files.extend(self._generate_m3u8_playlists(latest_segment, languages))

        return files

    def _generate_vtt_segments(
        self,
        started_at: datetime,
        transcripts: list[Transcript],
        new_segments: list[int],
        languages: set[str],
    ) -> list[tuple[str, str, str]]:
        """Generate VTT segment files."""
        files = []

        for seg_num in new_segments:
            # Original language segment
            vtt_content = generate_segment_webvtt(
                transcripts=transcripts,
                segment_num=seg_num,
                session_started_at=started_at,
                language=None,
            )
            files.append((f"captions-{seg_num}.vtt", vtt_content, "text/vtt"))

            # Translated segments
            for lang in languages:
                vtt_content_lang = generate_segment_webvtt(
                    transcripts=transcripts,
                    segment_num=seg_num,
                    session_started_at=started_at,
                    language=lang,
                )
                files.append((f"captions-{lang}-{seg_num}.vtt", vtt_content_lang, "text/vtt"))

        return files

    def _generate_m3u8_playlists(
        self,
        latest_segment: int,
        languages: set[str],
    ) -> list[tuple[str, str, str]]:
        """Generate M3U8 playlist files."""
        files: list[tuple[str, str, str]] = []

        # Keep only the last MAX_SEGMENTS segments in the playlist.
        media_sequence = max(0, latest_segment - MAX_SEGMENTS + 1)

        # Original language playlist
        files.append(
            (
                "captions.m3u8",
                self._build_m3u8_content(
                    media_sequence=media_sequence,
                    latest_segment=latest_segment,
                ),
                "application/vnd.apple.mpegurl",
            )
        )

        # Translated playlists
        for lang in languages:
            files.append(
                (
                    f"captions-{lang}.m3u8",
                    self._build_m3u8_content(
                        media_sequence=media_sequence,
                        latest_segment=latest_segment,
                        language=lang,
                    ),
                    "application/vnd.apple.mpegurl",
                )
            )

        return files

    def _build_m3u8_content(
        self,
        media_sequence: int,
        latest_segment: int,
        language: str | None = None,
    ) -> str:
        """Build M3U8 playlist content."""
        target_duration = math.ceil(SEGMENT_DURATION)
        lines = [
            "#EXTM3U",
            "#EXT-X-VERSION:3",
            f"#EXT-X-TARGETDURATION:{target_duration}",
            f"#EXT-X-MEDIA-SEQUENCE:{media_sequence}",
            "",
        ]

        for seg_num in range(media_sequence, latest_segment + 1):
            lines.append(f"#EXTINF:{SEGMENT_DURATION:.1f},")
            if language:
                lines.append(f"captions-{language}-{seg_num}.vtt")
            else:
                lines.append(f"captions-{seg_num}.vtt")

        return "\n".join(lines)
