"""Shared utilities for schema validation."""

from datetime import datetime
from typing import Any


def parse_mongo_datetime(v: Any) -> Any:
    """Parse MongoDB Extended JSON datetime format or return as-is if already datetime.

    MongoDB Extended JSON format: {'$date': '2024-11-01T08:00:00Z'}
    This can occur when data is inserted via mongoimport or other tools.
    """
    if isinstance(v, datetime):
        return v
    if isinstance(v, dict) and "$date" in v:
        return datetime.fromisoformat(v["$date"].replace("Z", "+00:00"))
    # Return as-is and let Pydantic handle validation
    return v
