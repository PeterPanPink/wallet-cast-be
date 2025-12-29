"""Test segmented VTT caption generation."""

import os
import time
from datetime import datetime, timezone

import pytest

from app.domain.live.session._caption_query import (
    MAX_SEGMENTS,
    SEGMENT_DURATION,
    calculate_segment_number,
    generate_segment_webvtt,
    get_segment_time_range,
)


def test_calculate_segment_number():
    """Test segment number calculation."""
    started_at = datetime.now(timezone.utc)
    base_ts = started_at.timestamp()

    # Test segment boundaries - time_seconds is absolute Unix timestamp
    assert calculate_segment_number(base_ts + 0.0, started_at) == 0
    assert calculate_segment_number(base_ts + 3.9, started_at) == 0
    assert calculate_segment_number(base_ts + 4.0, started_at) == 1
    assert calculate_segment_number(base_ts + 7.9, started_at) == 1
    assert calculate_segment_number(base_ts + 8.0, started_at) == 2
    assert calculate_segment_number(base_ts + 15.5, started_at) == 3


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Requires time.tzset()")
def test_calculate_segment_number_naive_started_at_assumes_utc() -> None:
    """Ensure tz-naive started_at is treated as UTC, independent of local timezone."""
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "US/Pacific"
    time.tzset()
    try:
        started_at_naive = datetime(2025, 1, 1, 0, 0, 0)  # tz-naive, represents UTC
        base_ts_utc = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()
        assert calculate_segment_number(base_ts_utc + 0.0, started_at_naive) == 0
        assert calculate_segment_number(base_ts_utc + 4.0, started_at_naive) == 1
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


def test_get_segment_time_range():
    """Test segment time range calculation."""
    assert get_segment_time_range(0) == (0.0, 4.0)
    assert get_segment_time_range(1) == (4.0, 8.0)
    assert get_segment_time_range(2) == (8.0, 12.0)
    assert get_segment_time_range(10) == (40.0, 44.0)


def test_segment_duration():
    """Test segment duration constant."""
    assert SEGMENT_DURATION == 4.0


def test_max_segments():
    """Test max segments constant."""
    assert MAX_SEGMENTS == 100


# Fixed session start time for tests
TEST_SESSION_START = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
TEST_SESSION_START_TS = TEST_SESSION_START.timestamp()


class MockTranscript:
    """Mock transcript for testing."""

    def __init__(self, text: str, start: float, end: float, translations: dict | None = None):
        self.text = text
        # Convert relative times to absolute timestamps
        self.start_time = TEST_SESSION_START_TS + start
        self.end_time = TEST_SESSION_START_TS + end
        self.translations = translations or {}


def test_generate_segment_webvtt_empty():
    """Test generating VTT segment with no transcripts."""
    result = generate_segment_webvtt([], 0, TEST_SESSION_START)
    assert "WEBVTT" in result
    # Should have header but no content
    lines = result.strip().split("\n")
    assert lines[0] == "WEBVTT"


def test_generate_segment_webvtt_single_transcript():
    """Test generating VTT segment with single transcript."""
    transcripts = [MockTranscript("Hello world", 1.0, 3.0)]

    result = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START)  # type: ignore
    assert "WEBVTT" in result
    assert "Hello world" in result
    assert "00:00:01.000 --> 00:00:03.000" in result


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Requires time.tzset()")
def test_generate_segment_webvtt_naive_started_at_assumes_utc() -> None:
    """Ensure tz-naive session_started_at is treated as UTC when computing offsets."""
    original_tz = os.environ.get("TZ")
    os.environ["TZ"] = "US/Pacific"
    time.tzset()
    try:
        started_at_naive = datetime(2025, 1, 1, 0, 0, 0)  # tz-naive, represents UTC
        base_ts_utc = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp()

        class _T:
            text = "Hello"
            translations = {}
            start_time = base_ts_utc + 1.0
            end_time = base_ts_utc + 3.0

        result = generate_segment_webvtt([_T()], 0, started_at_naive)  # type: ignore[arg-type]
        assert "Hello" in result
        assert "00:00:01.000 --> 00:00:03.000" in result
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()


def test_generate_segment_webvtt_overlapping_transcripts():
    """Test generating VTT segment with transcripts overlapping segment boundary."""
    transcripts = [
        MockTranscript("First", 0.5, 2.5),
        MockTranscript("Second", 2.5, 5.5),  # Overlaps segment 0 and 1
        MockTranscript("Third", 6.0, 8.0),  # In segment 1
    ]

    # Segment 0: [0.0, 4.0)
    result_seg0 = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START)  # type: ignore
    assert "First" in result_seg0
    assert "Second" in result_seg0
    assert "Third" not in result_seg0

    # Segment 1: [4.0, 8.0)
    result_seg1 = generate_segment_webvtt(transcripts, 1, TEST_SESSION_START)  # type: ignore
    assert "First" not in result_seg1
    assert "Second" in result_seg1
    assert "Third" in result_seg1


def test_generate_segment_webvtt_with_translation():
    """Test generating VTT segment with translation."""
    transcripts = [
        MockTranscript(
            "Hello world",
            1.0,
            3.0,
            translations={"es": "Hola mundo", "fr": "Bonjour le monde"},
        )
    ]

    # Original language
    result = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START, language=None)  # type: ignore
    assert "Hello world" in result

    # Spanish translation
    result_es = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START, language="es")  # type: ignore
    assert "Hola mundo" in result_es
    assert "Hello world" not in result_es

    # French translation
    result_fr = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START, language="fr")  # type: ignore
    assert "Bonjour le monde" in result_fr


def test_generate_segment_webvtt_clamped_times():
    """Test that times are clamped to segment boundaries."""
    transcripts = [MockTranscript("Overlapping", 2.0, 6.0)]  # Spans segments 0 and 1

    # In segment 0: should be clamped to [2.0, 4.0]
    result_seg0 = generate_segment_webvtt(transcripts, 0, TEST_SESSION_START)  # type: ignore
    assert "00:00:02.000 --> 00:00:04.000" in result_seg0

    # In segment 1: should be clamped to [4.0, 6.0]
    result_seg1 = generate_segment_webvtt(transcripts, 1, TEST_SESSION_START)  # type: ignore
    assert "00:00:04.000 --> 00:00:06.000" in result_seg1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
