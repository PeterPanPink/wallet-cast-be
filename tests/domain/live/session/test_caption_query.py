"""Tests for caption egress endpoints."""

from datetime import datetime, timezone

from app.domain.live.session._caption_query import (
    format_time_vtt,
    generate_m3u8_playlist,
    generate_webvtt,
)


# Mock Transcript class for testing without Beanie initialization
class MockTranscript:
    """Mock Transcript for testing."""

    def __init__(
        self,
        session_id: str,
        room_id: str,
        text: str,
        start_time: float,
        end_time: float,
        duration: float,
        created_at: datetime,
        language: str | None = None,
        translations: dict[str, str] | None = None,
        confidence: float | None = None,
        speaker_id: str | None = None,
        participant_identity: str | None = None,
    ):
        self.session_id = session_id
        self.room_id = room_id
        self.text = text
        self.start_time = start_time
        self.end_time = end_time
        self.duration = duration
        self.created_at = created_at
        self.language = language
        self.translations = translations
        self.confidence = confidence
        self.speaker_id = speaker_id
        self.participant_identity = participant_identity


class TestFormatTimeVTT:
    """Tests for WebVTT time formatting."""

    def test_format_zero_seconds(self):
        """Test formatting 0 seconds."""
        assert format_time_vtt(0.0) == "00:00:00.000"

    def test_format_with_milliseconds(self):
        """Test formatting with milliseconds."""
        assert format_time_vtt(1.234) == "00:00:01.234"

    def test_format_with_minutes(self):
        """Test formatting with minutes."""
        assert format_time_vtt(65.5) == "00:01:05.500"

    def test_format_with_hours(self):
        """Test formatting with hours."""
        assert format_time_vtt(3665.123) == "01:01:05.123"


class TestGenerateWebVTT:
    """Tests for WebVTT generation."""

    def test_empty_transcripts(self):
        """Test generating WebVTT with no transcripts."""
        session_started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        result = generate_webvtt([], session_started_at)
        assert result.startswith("WEBVTT\n")

    def test_single_transcript(self):
        """Test generating WebVTT with a single transcript."""
        # Session started at 12:00:00 UTC
        session_started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        # Transcript at 12:00:01 (1 second after session start)
        transcript_time = session_started_at.timestamp() + 1.0

        transcript = MockTranscript(
            session_id="se_123",
            room_id="rm_123",
            text="Hello world",
            start_time=transcript_time,  # Absolute timestamp
            end_time=transcript_time + 2.0,  # 2 seconds duration
            duration=2.0,
            created_at=datetime.now(timezone.utc),
        )
        result = generate_webvtt([transcript], session_started_at)  # type: ignore[arg-type]

        assert "WEBVTT" in result
        # Should show relative time from session start (1 second)
        assert "00:00:01.000 --> 00:00:03.000" in result
        assert "Hello world" in result

    def test_multiple_transcripts(self):
        """Test generating WebVTT with multiple transcripts."""
        session_started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        base_time = session_started_at.timestamp()

        transcripts = [
            MockTranscript(
                session_id="se_123",
                room_id="rm_123",
                text="First line",
                start_time=base_time + 1.0,
                end_time=base_time + 3.0,
                duration=2.0,
                created_at=datetime.now(timezone.utc),
            ),
            MockTranscript(
                session_id="se_123",
                room_id="rm_123",
                text="Second line",
                start_time=base_time + 4.0,
                end_time=base_time + 6.0,
                duration=2.0,
                created_at=datetime.now(timezone.utc),
            ),
        ]
        result = generate_webvtt(transcripts, session_started_at)  # type: ignore[arg-type]

        assert "First line" in result
        assert "Second line" in result
        assert result.count("\n\n") >= 2  # Empty lines between cues

    def test_translation_output(self):
        """Test generating WebVTT with translations."""
        session_started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        transcript_time = session_started_at.timestamp() + 1.0

        transcript = MockTranscript(
            session_id="se_123",
            room_id="rm_123",
            text="Hello world",
            translations={"es": "Hola mundo", "fr": "Bonjour le monde"},
            start_time=transcript_time,
            end_time=transcript_time + 2.0,
            duration=2.0,
            created_at=datetime.now(timezone.utc),
        )
        result = generate_webvtt([transcript], session_started_at, language="es")  # type: ignore[arg-type]

        assert "Hola mundo" in result
        assert "Hello world" not in result

    def test_translation_missing_falls_back_to_original(self):
        """Test that missing translation uses original text."""
        session_started_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        transcript_time = session_started_at.timestamp() + 1.0

        transcript = MockTranscript(
            session_id="se_123",
            room_id="rm_123",
            text="Hello world",
            translations={"es": "Hola mundo"},
            start_time=transcript_time,
            end_time=transcript_time + 2.0,
            duration=2.0,
            created_at=datetime.now(timezone.utc),
        )
        result = generate_webvtt([transcript], session_started_at, language="fr")  # type: ignore[arg-type]

        # Should use original since French translation not available
        assert "Hello world" in result


class TestGenerateM3U8Playlist:
    """Tests for M3U8 playlist generation."""

    def test_basic_playlist(self):
        """Test generating basic M3U8 playlist."""
        result = generate_m3u8_playlist(
            session_id="se_123",
            base_url="https://api.example.com",
        )

        assert "#EXTM3U" in result
        assert "#EXT-X-VERSION:3" in result
        assert "TYPE=SUBTITLES" in result
        assert "se_123/captions.vtt" in result

    def test_playlist_with_languages(self):
        """Test generating M3U8 playlist with multiple languages."""
        result = generate_m3u8_playlist(
            session_id="se_123",
            base_url="https://api.example.com",
            languages=["es", "fr", "ja"],
        )

        assert "se_123/captions.vtt?language=es" in result
        assert "se_123/captions.vtt?language=fr" in result
        assert "se_123/captions.vtt?language=ja" in result
        assert 'NAME="Es"' in result or 'NAME="ES"' in result.upper()

    def test_playlist_default_track(self):
        """Test that default track is marked correctly."""
        result = generate_m3u8_playlist(
            session_id="se_123",
            base_url="https://api.example.com",
        )

        # Default track should be marked as default and autoselect
        assert "DEFAULT=YES" in result
        assert "AUTOSELECT=YES" in result
