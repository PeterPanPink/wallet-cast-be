"""Shared serialization utilities for API schemas."""

from datetime import datetime, timezone


def serialize_utc_datetime(dt: datetime) -> str:
    """Serialize datetime as ISO 8601 string with UTC timezone.

    If the datetime is naive (no timezone info), it is assumed to be UTC.
    Output format: 2025-12-03T10:30:00+00:00
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def serialize_optional_utc_datetime(dt: datetime | None) -> str | None:
    """Serialize optional datetime as ISO 8601 string with UTC timezone."""
    if dt is None:
        return None
    return serialize_utc_datetime(dt)
