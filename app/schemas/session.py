"""Session ODM schema."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from beanie import Document, Indexed
from beanie.odm.fields import ExpressionField
from beanie.odm.operators.update.general import Set
from loguru import logger
from pydantic import Field, field_validator
from pymongo import IndexModel

from app.utils.app_errors import AppError, AppErrorCode, HttpStatusCode

from .schema_utils import parse_mongo_datetime
from .session_runtime import SessionRuntime
from .session_state import SessionState


class Session(Document):
    """Session document model."""

    session_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    room_id: Indexed(str, unique=True)  # type: ignore[valid-type]
    channel_id: str
    user_id: str

    # Session descriptor fields
    title: str | None = None
    location: str | None = None
    description: str | None = None
    cover: str | None = None
    lang: str | None = None
    category_ids: list[str] | None = None

    # Session settings
    status: SessionState = SessionState.IDLE
    max_participants: int | None = None

    # Provider configuration
    runtime: SessionRuntime = Field(default_factory=SessionRuntime)

    # Caption upload tracking
    caption_last_uploaded_segment: int | None = None  # Last segment number uploaded to S3
    caption_s3_urls: dict[str, str] | None = (
        None  # Map of file type/language to S3 URLs (e.g., "master.m3u8", "en.m3u8", "segment-0")
    )

    # Timestamps
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    stopped_at: datetime | None = None

    # Version control for optimistic locking
    version: int = Field(default=1)

    @field_validator("created_at", "updated_at", "started_at", "stopped_at", mode="before")
    @classmethod
    def _parse_datetime(cls, v: Any) -> Any:
        """Parse MongoDB Extended JSON datetime format."""
        return parse_mongo_datetime(v)

    def _build_update_fields(self) -> dict[ExpressionField, Any]:
        data = self.model_dump()
        data.pop("id", None)
        update_fields: dict[ExpressionField, Any] = {}
        for field_name, value in data.items():
            session_field = getattr(Session, field_name, None)
            if session_field is not None:
                update_fields[session_field] = value
        return update_fields

    async def _raise_version_conflict(self, current_version: int) -> None:
        fresh_session = await Session.get(self.id)
        error_msg = (
            f"Version conflict on session {self.session_id}\n"
            f"Expected version: {current_version}, Current version: "
            f"{fresh_session.version if fresh_session else 'N/A'}\n"
            f"Current session data: status={fresh_session.status if fresh_session else 'N/A'}, "
            f"version={fresh_session.version if fresh_session else 'N/A'}"
        )
        logger.warning(error_msg)
        raise AppError(
            errcode=AppErrorCode.E_SESSION_VERSION_CONFLICT,
            errmesg=error_msg,
            status_code=HttpStatusCode.CONFLICT,
        )

    async def save_session_with_version_check(self) -> bool:
        """Save session with optimistic locking using version field.

        Raises AppError on version conflict.

        Returns:
            True if save succeeded.

        Raises:
            AppError: If version conflict occurred (E_SESSION_VERSION_CONFLICT).
        """
        # Initialize version if missing (for backward compatibility)
        if self.version is None:
            self.version = 1

        current_version = self.version
        self.version = current_version + 1
        update_fields = self._build_update_fields()

        # Try to update with version check (handle None for backward compatibility)
        if current_version == 1:
            # First update: match both version=1 and version=None (missing field)
            result = await Session.find(
                Session.id == self.id,
                {"$or": [{"version": 1}, {"version": None}]},  # type: ignore[arg-type]
            ).update(Set(update_fields))  # type: ignore[arg-type]
        else:
            # Subsequent updates: strict version match
            result = await Session.find(
                Session.id == self.id,
                Session.version == current_version,
            ).update(Set(update_fields))  # type: ignore[arg-type]

        if result and result.modified_count > 0:
            logger.debug(
                f"Session {self.session_id} saved successfully "
                f"(version {current_version} -> {current_version + 1})"
            )
            return True

        # Version conflict - another update happened concurrently
        await self._raise_version_conflict(current_version)
        return False

    async def partial_update_session_with_version_check(
        self,
        updates: Mapping[ExpressionField, Any],
        max_retry_on_conflicts: int = 0,
    ) -> bool:
        """Atomically update select session fields with optimistic locking.

        Args:
            updates: Mapping of Session field expressions to values.
                Example: {Session.status: SessionState.READY}
            max_retry_on_conflicts: Maximum number of retries on version conflict (0-10).
                On conflict, refreshes session from DB and retries. Defaults to 0 (no retry).

        Returns:
            True if update succeeded.

        Raises:
            AppError: If version conflict occurred after all retries (E_SESSION_VERSION_CONFLICT),
                or if updates include Session.version or max_retry_on_conflicts is invalid (E_INVALID_REQUEST).
        """
        if Session.version in updates:
            raise AppError(
                AppErrorCode.E_INVALID_REQUEST,
                "updates must not include Session.version",
                HttpStatusCode.BAD_REQUEST,
            )

        if Session.status in updates and max_retry_on_conflicts > 0:
            raise AppError(
                AppErrorCode.E_INVALID_REQUEST,
                "retries not allowed when updating status (critical field)",
                HttpStatusCode.BAD_REQUEST,
            )

        if max_retry_on_conflicts < 0 or max_retry_on_conflicts > 10:
            raise AppError(
                AppErrorCode.E_INVALID_REQUEST,
                "max_retry_on_conflicts must be between 0 and 10",
                HttpStatusCode.BAD_REQUEST,
            )

        attempts = 0
        max_attempts = max_retry_on_conflicts + 1

        while attempts < max_attempts:
            attempts += 1

            if self.version is None:
                self.version = 1

            current_version = self.version
            new_version = current_version + 1
            update_fields = dict(updates)
            update_fields[Session.version] = new_version  # type: ignore

            if current_version == 1:
                result = await Session.find(
                    Session.id == self.id,
                    {"$or": [{"version": 1}, {"version": None}]},  # type: ignore[arg-type]
                ).update(Set(update_fields))  # type: ignore[arg-type]
            else:
                result = await Session.find(
                    Session.id == self.id,
                    Session.version == current_version,
                ).update(Set(update_fields))  # type: ignore[arg-type]

            if result and result.modified_count > 0:
                self.version = new_version
                logger.debug(
                    f"Session {self.session_id} partially updated successfully "
                    f"(version {current_version} -> {new_version})"
                )
                return True

            # Version conflict - refresh and retry if attempts remain
            if attempts < max_attempts:
                fresh_session = await Session.get(self.id)
                if fresh_session is None:
                    await self._raise_version_conflict(current_version)
                    return False
                self.version = fresh_session.version
                logger.debug(
                    f"Session {self.session_id} version conflict, retrying "
                    f"(attempt {attempts}/{max_attempts}, refreshed version: {self.version})"
                )
                continue

            await self._raise_version_conflict(current_version)
            return False

        return False

    class Settings:
        name = "session"
        indexes = [
            [("session_id", 1)],  # unique handled by Indexed
            [("room_id", 1)],  # unique handled by Indexed
            IndexModel(
                [("channel_id", 1)],
                partialFilterExpression={
                    "status": {"$in": ["idle", "ready", "publishing", "live", "ending"]},
                    "stopped_at": None,
                },
                unique=True,
                name="channel_id_active_unique",
            ),
            IndexModel(
                [("started_at", -1), ("_id", -1)],
                partialFilterExpression={"status": "live"},
                name="started_at_id_live_partial",
            ),
        ]
