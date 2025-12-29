"""Channel ODM schema."""

from datetime import datetime
from typing import Annotated, Any

from beanie import Document, Indexed
from pydantic import Field, field_validator

from .schema_utils import parse_mongo_datetime
from .user_configs import UserConfigs


class Channel(Document):
    """Channel document model."""

    channel_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    user_id: Indexed(str)  # type: ignore[valid-type]

    # Channel descriptor fields
    title: str | None = None
    location: str | None = None  # ISO 3166-1 alpha-2 country code
    description: str | None = None
    cover: str | None = None
    lang: str | None = None  # ISO 639-1 language code
    category_ids: Annotated[list[str] | None, Indexed()] = None

    # Provider configurations
    user_configs: UserConfigs = Field(default_factory=UserConfigs)
    # Timestamps
    created_at: datetime
    updated_at: datetime

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def _parse_datetime(cls, v: Any) -> Any:
        """Parse MongoDB Extended JSON datetime format."""
        return parse_mongo_datetime(v)

    class Settings:
        name = "channel"
        indexes = [
            "user_id",
            [("channel_id", 1)],  # unique handled by Indexed
            "category_ids",
        ]
