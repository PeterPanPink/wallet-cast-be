"""Transcript ODM schema for storing caption transcriptions."""

from datetime import datetime
from typing import Any

from beanie import Document, Indexed
from pydantic import Field, field_validator
from pymongo import ASCENDING, DESCENDING, IndexModel

from .schema_utils import parse_mongo_datetime


class Transcript(Document):
    """Transcript document model for storing final transcriptions.

    This collection stores all final transcript segments from live sessions,
    including timing information and metadata for caption playback and analysis.
    """

    # Foreign keys
    session_id: Indexed(str)  # type: ignore[valid-type]
    room_id: str

    # Transcript content
    text: str
    language: str | None = None
    confidence: float | None = None
    translations: dict[str, str] | None = None  # Map of language code to translated text

    # Timing information (Unix timestamps in UTC - absolute time, NOT relative offsets)
    # These are converted to relative offsets (from session.started_at) for WebVTT generation
    start_time: float  # Absolute Unix timestamp (UTC) when speech started
    end_time: float  # Absolute Unix timestamp (UTC) when speech ended
    duration: float  # Duration of the speech segment in seconds

    # Speaker information (if available)
    speaker_id: str | None = None
    participant_identity: str | None = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("created_at", mode="before")
    @classmethod
    def _parse_datetime(cls, v: Any) -> Any:
        """Parse MongoDB Extended JSON datetime format."""
        return parse_mongo_datetime(v)

    class Settings:
        name = "transcript"
        indexes = [
            IndexModel(
                [("session_id", ASCENDING), ("start_time", ASCENDING)],
                name="idx_session_time",
            ),
            IndexModel(
                [("room_id", ASCENDING), ("created_at", DESCENDING)],
                name="idx_room_created",
            ),
            IndexModel(
                [("created_at", DESCENDING)],
                name="idx_created_desc",
            ),
        ]
